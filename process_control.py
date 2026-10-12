"""PID-lock and stop-flag lifecycle control shared by main.py (writes/checks the lock,
watches the stop flag) and toggle.py (the desktop on/off switch).

A lock file alone is not enough to know Phone Watcher is running: if it crashed, the PID
in the file may now belong to an unrelated process (Windows reuses PIDs), so every check
here also verifies the live process's command line actually looks like our own main.py
before trusting the lock.
"""

import os
import time
from pathlib import Path

import psutil as _real_psutil

_PROCESS_MARKERS = ("main.py", "phonewatcher")


def write_lock(lock_path: Path) -> None:
    lock_path.write_text(str(os.getpid()), encoding="utf-8")


def remove_file_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def read_lock_pid(lock_path: Path) -> int | None:
    try:
        return int(lock_path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError, OSError):
        return None


def is_phone_watcher_process(pid: int, psutil_module=_real_psutil) -> bool:
    """True if `pid` is alive and its command line looks like our own main.py.

    Guards against a stale lock (crash) or Windows reusing the PID for an unrelated process.
    """
    try:
        process = psutil_module.Process(pid)
    except psutil_module.NoSuchProcess:
        return False
    try:
        if not process.is_running():
            return False
        cmdline = " ".join(process.cmdline()).lower()
    except (psutil_module.NoSuchProcess, psutil_module.AccessDenied, psutil_module.ZombieProcess):
        # The process can vanish between is_running() and cmdline() (e.g. a fast, clean
        # exit racing this check) -- that's just it having already stopped, not an error.
        return False
    return any(marker in cmdline for marker in _PROCESS_MARKERS)


def get_running_pid(lock_path: Path, psutil_module=_real_psutil) -> int | None:
    """Return the PID of a live, matching Phone Watcher process, or None.

    A lock file pointing at a dead or unrelated process is a stale leftover (typically from
    a crash) and is removed here so callers never have to special-case it.
    """
    pid = read_lock_pid(lock_path)
    if pid is None:
        return None
    if is_phone_watcher_process(pid, psutil_module=psutil_module):
        return pid
    remove_file_if_exists(lock_path)
    return None


def request_stop(stop_flag_path: Path) -> None:
    stop_flag_path.write_text("stop", encoding="utf-8")


def wait_for_exit(lock_path: Path, pid: int, timeout_seconds: float, psutil_module=_real_psutil) -> bool:
    """Poll until the process is gone or the timeout elapses. Returns True if it exited."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not is_phone_watcher_process(pid, psutil_module=psutil_module):
            return True
        time.sleep(0.2)
    return not is_phone_watcher_process(pid, psutil_module=psutil_module)


def force_kill(pid: int, psutil_module=_real_psutil) -> None:
    try:
        process = psutil_module.Process(pid)
        process.kill()
    except psutil_module.NoSuchProcess:
        pass
