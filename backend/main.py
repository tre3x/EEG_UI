# backend/main.py
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import io
import os
import pandas as pd
from typing import List, Optional, Tuple
from .processing import load_edf, segment_signal
from .inference import eeg_inference

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

START_TIME_KEYS = ['Start time', 'Start Time', 'start time', 'start time ']
END_TIME_KEYS = ['End time', 'End Time', 'end time', 'end time ']


def _sanitize_meas_date(meas_date: Optional[pd.Timestamp]) -> Optional[pd.Timestamp]:
    if meas_date is None:
        return None
    meas_start = pd.Timestamp(meas_date)
    # Drop timezone info to align with Excel exports
    if meas_start.tzinfo is not None:
        meas_start = meas_start.tz_convert(None)
    return meas_start


def _extract_column_names(gt_df: Optional[pd.DataFrame]) -> Tuple[str, str]:
    """
    Determine which column names to use when exporting predictions.
    If a ground truth sheet is supplied, mirror its start/end labels.
    Otherwise default to the canonical names.
    """
    if gt_df is not None:
        start_col = next((key for key in START_TIME_KEYS if key in gt_df.columns), None)
        end_col = next((key for key in END_TIME_KEYS if key in gt_df.columns), None)
        if start_col and end_col:
            return start_col, end_col
    return START_TIME_KEYS[0], END_TIME_KEYS[0]


def _format_timestamp(meas_start: Optional[pd.Timestamp], seconds_offset: float) -> str:
    if meas_start is None:
        # Fallback to seconds offset when absolute timestamps are unavailable
        return f"{seconds_offset:.2f}"
    timestamp = meas_start + pd.to_timedelta(seconds_offset, unit="s")
    return timestamp.strftime("%m/%d/%Y %H:%M:%S")


def _build_prediction_intervals(predictions, times, window_length, meas_start):
    """
    Convert per-window predictions into seizure intervals expressed as seconds offsets.
    """
    if len(times) > 1:
        sample_interval = float(times[1] - times[0])
    else:
        sample_interval = 1.0  # fallback to 1 Hz if metadata missing
    window_duration = window_length * sample_interval
    window_start_time = float(times[0]) if len(times) else 0.0
    
    intervals = []
    active_start_idx = None

    for idx, label in enumerate(predictions):
        if label == "Seizure" and active_start_idx is None:
            active_start_idx = idx
        elif label != "Seizure" and active_start_idx is not None:
            intervals.append((active_start_idx, idx))
            active_start_idx = None

    if active_start_idx is not None:
        intervals.append((active_start_idx, len(predictions)))

    formatted_intervals = []
    for start_idx, end_idx in intervals:
        start_offset = window_start_time + start_idx * window_duration
        end_offset = window_start_time + end_idx * window_duration
        formatted_intervals.append(
            (
                _format_timestamp(meas_start, start_offset),
                _format_timestamp(meas_start, end_offset)
            )
        )
    return formatted_intervals


def _timestamp_to_iso(ts: Optional[pd.Timestamp]) -> Optional[str]:
    if ts is None:
        return None
    if ts.tzinfo is not None:
        ts = ts.tz_convert(None)
    return ts.isoformat(timespec="seconds")


def _parse_datetime(value: Optional[str]) -> Optional[pd.Timestamp]:
    if value in (None, "", "null"):
        return None
    try:
        ts = pd.to_datetime(value)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid date-time value: {value}")
    if ts.tzinfo is not None:
        ts = ts.tz_convert(None)
    return ts


def _filter_signal_by_range(signal, times, meas_start, start_ts, end_ts):
    if start_ts is None and end_ts is None:
        return signal, times
    if meas_start is None:
        # Cannot align to absolute timestamps without measurement start
        return signal[0:0], times[0:0]
    abs_times = meas_start + pd.to_timedelta(times, unit="s")
    mask = pd.Series(True, index=range(len(abs_times)))
    if start_ts is not None:
        mask &= abs_times >= start_ts
    if end_ts is not None:
        mask &= abs_times <= end_ts
    mask = mask.to_numpy()
    return signal[mask], times[mask]


def _collect_uploads(edf_files: List[UploadFile], edf_file: Optional[UploadFile]) -> List[UploadFile]:
    uploads: List[UploadFile] = []
    if edf_files:
        uploads.extend(edf_files)
    if edf_file is not None:
        uploads.append(edf_file)
    return uploads


def _base_filename(original_name: Optional[str], fallback: str) -> str:
    if not original_name:
        return fallback
    base = os.path.splitext(os.path.basename(original_name))[0]
    return base or fallback


def _make_sheet_name(filename: Optional[str], idx: int, used: set) -> str:
    """
    Create an Excel-safe sheet name (<=31 chars, unique).
    """
    base = _base_filename(filename, f"File{idx}")
    base = base.replace("\\", "_").replace("/", "_")
    candidate = base[:31] or f"File{idx}"
    suffix = 1
    while candidate in used:
        suffix_str = f"_{suffix}"
        trunc_length = 31 - len(suffix_str)
        candidate = (base[:trunc_length] if trunc_length > 0 else f"File{idx}") + suffix_str
        suffix += 1
    return candidate


def _derive_export_name(results_by_file) -> str:
    if len(results_by_file) == 1:
        return _base_filename(results_by_file[0][0], "predictions")
    return "batch"


@app.post("/ranges")
async def get_available_ranges(
    edf_files: List[UploadFile] = File(None),
    edf_file: UploadFile = File(None),
):
    uploads = _collect_uploads(edf_files, edf_file)
    if not uploads:
        raise HTTPException(status_code=400, detail="Please upload at least one EDF file.")

    file_ranges = []
    for idx, upload in enumerate(uploads, start=1):
        filename = upload.filename or f"file_{idx}"
        if not filename.lower().endswith(".edf"):
            continue
        file_bytes = await upload.read()
        if not file_bytes:
            continue
        file_buffer = io.BytesIO(file_bytes)
        try:
            signal, times, meas_date = load_edf(file_buffer, crop_duration=None)
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to read EDF file '{filename}': {exc}",
            ) from exc
        if len(times) == 0:
            continue
        meas_start = _sanitize_meas_date(meas_date)
        if meas_start is None:
            continue
        file_start = meas_start + pd.to_timedelta(times[0], unit="s")
        file_end = meas_start + pd.to_timedelta(times[-1], unit="s")
        file_ranges.append(
            {
                "name": filename,
                "start": file_start,
                "end": file_end,
            }
        )

    if not file_ranges:
        raise HTTPException(
            status_code=400,
            detail="No EDF files with valid measurement timestamps were found.",
        )

    overall_start = min(entry["start"] for entry in file_ranges)
    overall_end = max(entry["end"] for entry in file_ranges)

    response = {
        "files": [
            {
                "name": entry["name"],
                "start": _timestamp_to_iso(entry["start"]),
                "end": _timestamp_to_iso(entry["end"]),
            }
            for entry in file_ranges
        ],
        "overall_start": _timestamp_to_iso(overall_start),
        "overall_end": _timestamp_to_iso(overall_end),
    }
    return response


@app.post("/process")
async def process_edf(
    edf_files: List[UploadFile] = File(None),
    edf_file: UploadFile = File(None),
    window_length: int = Form(...),
    analysis_start: str = Form(None),
    analysis_end: str = Form(None),
    gt_excel: UploadFile = File(None)
):
    uploads = _collect_uploads(edf_files, edf_file)
    if not uploads:
        raise HTTPException(status_code=400, detail="Please upload at least one EDF file.")

    analysis_start_ts = _parse_datetime(analysis_start)
    analysis_end_ts = _parse_datetime(analysis_end)
    if analysis_start_ts and analysis_end_ts and analysis_start_ts > analysis_end_ts:
        raise HTTPException(status_code=400, detail="Analysis start must be before end time.")

    gt_df = None
    if gt_excel is not None:
        gt_content = await gt_excel.read()
        if gt_content:
            gt_df = pd.read_excel(io.BytesIO(gt_content))

    start_col, end_col = _extract_column_names(gt_df)

    loaded_files = []
    for idx, upload in enumerate(uploads, start=1):
        filename = upload.filename or f"file_{idx}"
        if not filename.lower().endswith(".edf"):
            continue
        file_bytes = await upload.read()
        if not file_bytes:
            continue
        file_buffer = io.BytesIO(file_bytes)
        try:
            signal, times, meas_date = load_edf(file_buffer, crop_duration=None)
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to read EDF file '{filename}': {exc}",
            ) from exc
        loaded_files.append(
            {
                "filename": filename,
                "signal": signal,
                "times": times,
                "meas_start": _sanitize_meas_date(meas_date),
                "order": idx,
            }
        )

    if not loaded_files:
        raise HTTPException(status_code=400, detail="No valid EDF data found in the upload.")

    loaded_files.sort(
        key=lambda entry: (
            entry["meas_start"] is None,
            entry["meas_start"] or pd.Timestamp.max,
            entry["order"],
        )
    )

    results_by_file = []
    for entry in loaded_files:
        filename = entry["filename"]
        signal = entry["signal"]
        times = entry["times"]
        meas_start = entry["meas_start"]

        filtered_signal, filtered_times = _filter_signal_by_range(
            signal, times, meas_start, analysis_start_ts, analysis_end_ts
        )
        if len(filtered_signal) == 0 or len(filtered_times) == 0:
            continue

        windows = segment_signal(filtered_signal, window_length)
        if len(windows) == 0:
            continue
        predictions = eeg_inference.predict_windows(windows)
        intervals = _build_prediction_intervals(
            predictions, filtered_times, window_length, meas_start
        )
        results_by_file.append((filename, intervals))

    if not results_by_file:
        raise HTTPException(
            status_code=400,
            detail="No samples matched the selected analysis window.",
        )

    buffer = io.BytesIO()
    if len(results_by_file) == 1:
        _, intervals = results_by_file[0]
        pd.DataFrame(intervals, columns=[start_col, end_col]).to_excel(buffer, index=False)
    else:
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            used_sheet_names = set()
            for idx, (name, intervals) in enumerate(results_by_file, start=1):
                safe_name = _make_sheet_name(name, idx, used_sheet_names)
                used_sheet_names.add(safe_name)
                pd.DataFrame(intervals, columns=[start_col, end_col]).to_excel(
                    writer, sheet_name=safe_name, index=False
                )
    buffer.seek(0)

    filename = _derive_export_name(results_by_file)
    filename = f"{filename}_predictions.xlsx"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)


#uvicorn backend.main:app --reload

