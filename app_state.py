"""Shared in-process state connecting the tray icon, the external stop signal (from
toggle.py, via process_control's stop-flag file), and the detection loop -- all within the
single running Phone Watcher process."""

import threading


class AppState:
    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.tray_paused_event = threading.Event()  # tray Pause/Resume: fully releases the camera
        self.hide_preview_event = threading.Event()  # tray Show/Hide preview: monitoring keeps running
