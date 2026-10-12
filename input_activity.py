"""Local-only system idle-time tracking.

This reads only the OS-level timestamp of the last keyboard/mouse event, via the
Win32 GetLastInputInfo API. No key codes, mouse positions, window titles, or any
other input content is ever read, logged, or written to disk -- only "how many
seconds ago was the last input", which never leaves this process.
"""

import ctypes
from ctypes import wintypes


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def get_idle_seconds() -> float:
    """Return seconds elapsed since the last system-wide keyboard or mouse input."""
    info = _LastInputInfo()
    info.cbSize = ctypes.sizeof(_LastInputInfo)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    tick_count = ctypes.windll.kernel32.GetTickCount()
    # Both values are 32-bit unsigned ms-since-boot counters; masking handles their
    # (rare, ~49.7 day uptime) wraparound consistently.
    idle_millis = (tick_count - info.dwTime) & 0xFFFFFFFF
    return idle_millis / 1000.0
