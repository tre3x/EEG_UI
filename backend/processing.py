# backend/processing.py
import numpy as np
import mne
import os
import tempfile

def load_edf(file_obj, crop_duration=None):
    """
    Load an EDF file from a file-like object by writing it to a temporary file.
    Optionally crop the data to the first `crop_duration` seconds to speed up debugging.
    Returns the signal, time array, and measurement start time.
    """
    file_obj.seek(0)
    with tempfile.NamedTemporaryFile(suffix=".edf", delete=False) as tmp:
        tmp.write(file_obj.read())
        tmp.flush()
        tmp_filename = tmp.name

    # Read without preloading the entire file
    raw = mne.io.read_raw_edf(tmp_filename, preload=False, verbose=False)
    meas_date = raw.info.get('meas_date')  # measurement start time (a datetime or None)
    
    if crop_duration is not None:
        raw.crop(tmin=0, tmax=crop_duration)
    raw.load_data()
    os.remove(tmp_filename)
    
    # For simplicity, we take the first channel.
    signal, times = raw[0]
    return signal[0], times, meas_date

def segment_signal(signal, window_length):
    """
    Segment the signal into non-overlapping windows.
    """
    num_points = len(signal)
    num_windows = num_points // window_length
    # Reshape and drop remainder if any
    windows = signal[:num_windows * window_length].reshape(num_windows, window_length)
    return windows
