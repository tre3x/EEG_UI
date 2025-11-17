# EEG_UI

Simple EEG seizure prediction demo with a FastAPI backend for EDF ingestion/inference and a lightweight Flask UI for uploading recordings and downloading Excel exports.

## Prerequisites
- Python 3.10+
- A trained GRU checkpoint (update `MODEL_SAVE_PATH` in `backend/inference.py` to point to your `.pth` file)
- Virtualenv/conda recommended

## Installation
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install fastapi uvicorn[standard] flask pandas numpy torch mne openpyxl python-multipart
```

## Backend (API)
1. Ensure `backend/inference.py` has a valid `MODEL_SAVE_PATH`.
2. From the repo root, start the API:
   ```bash
   uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
   ```
3. Endpoints:
   - `POST /ranges` — returns available measurement time ranges per EDF file.
   - `POST /process` — accepts EDF uploads (and optional ground-truth Excel) and returns an Excel of predicted intervals.

## Frontend (Flask UI)
1. With the backend running on `http://127.0.0.1:8000`, start the UI:
   ```bash
   python frontend/app.py
   ```
2. Open `http://127.0.0.1:8050` in a browser to upload EDF files, pick an analysis window, and download prediction spreadsheets.

## Project Structure
- `backend/` — FastAPI app, EDF loading, segmentation, and GRU inference.
- `frontend/` — Minimal Flask single-page UI that talks to the backend.

## Notes
- `window_length` controls the non-overlapping segment size used for inference.
- Ground-truth Excel sheets (optional) can be uploaded so the export mirrors their start/end column names.
