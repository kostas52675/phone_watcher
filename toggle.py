"""Desktop on/off switch for Phone Watcher.

Launched by the "Phone Watcher" desktop shortcut (via pythonw.exe, so no console window
ever appears). Each run toggles: if Phone Watcher is not running, it starts it (camera
preview + monitoring + tray icon); if it is already running, it asks it to stop cleanly
(so the camera gets released and any punishment video window closes), force-killing it
only if it doesn't exit in time.
"""

import subprocess
import sys
from pathlib import Path

import config
import process_control as pc

STOP_TIMEOUT_SECONDS = 8.0


def _python_executable() -> Path:
    pythonw = config.PROJECT_ROOT / ".venv" / "Scripts" / "pythonw.exe"
    if pythonw.is_file():
        return pythonw
    print(f"[toggle] {pythonw} not found; falling back to {sys.executable}.", file=sys.stderr)
    return Path(sys.executable)


def stop_running(pid: int) -> None:
    print(f"Phone Watcher is running (PID {pid}). Stopping...")
    pc.request_stop(config.STOP_FLAG_FILE)
    if pc.wait_for_exit(config.LOCK_FILE, pid, timeout_seconds=STOP_TIMEOUT_SECONDS):
        print("Stopped cleanly.")
    else:
        print("Did not stop in time; forcing.")
        pc.force_kill(pid)
    pc.remove_file_if_exists(config.LOCK_FILE)
    pc.remove_file_if_exists(config.STOP_FLAG_FILE)


def start_new() -> None:
    pc.remove_file_if_exists(config.STOP_FLAG_FILE)  # clear any leftover flag from a prior run
    python_exe = _python_executable()
    main_script = config.PROJECT_ROOT / "main.py"
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    # pythonw has no console to print to, so route stdout/stderr to a log file instead of
    # DEVNULL -- otherwise a crash while running detached would be completely invisible.
    log_file = open(config.LOG_FILE, "a", encoding="utf-8", buffering=1)
    try:
        subprocess.Popen(
            [str(python_exe), "-u", str(main_script)],  # unbuffered, so the log fills in real time
            cwd=str(config.PROJECT_ROOT),
            creationflags=creationflags,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=log_file,
            close_fds=True,
        )
    finally:
        log_file.close()
    print("Phone Watcher started.")


def main() -> int:
    pid = pc.get_running_pid(config.LOCK_FILE)
    if pid is not None:
        stop_running(pid)
    else:
        start_new()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
