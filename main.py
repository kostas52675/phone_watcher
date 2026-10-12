"""Entry point for the local phone / doomscroll watcher."""

import argparse
import os
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2

import calibration
import config
import process_control
import tray
from app_state import AppState
from detector import WatcherDetector
from input_activity import get_idle_seconds
from notifier import play_notification
from punishment import PunishmentPlayer
from state_machine import DoomscrollStateMachine

_STATUS_LABELS = {
    "monitoring": "Monitoring",
    "looking_down": "LOOKING DOWN",
    "phone_detected": "PHONE DETECTED",
    "paused": "PAUSED",
}
_STATUS_COLORS = {
    "monitoring": (80, 220, 100),
    "looking_down": (0, 200, 255),
    "phone_detected": (0, 120, 255),
    "paused": (200, 200, 200),
}

_WINDOW_NAME = "Phone Watcher - press q to quit"


def build_state_machine() -> DoomscrollStateMachine:
    return DoomscrollStateMachine(
        phone_sustain_seconds=config.PHONE_SUSTAIN_SECONDS,
        gaze_idle_input_seconds=config.GAZE_IDLE_INPUT_SECONDS,
        gaze_sustain_seconds=config.GAZE_SUSTAIN_SECONDS,
        cooldown_seconds=config.COOLDOWN_SECONDS,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local webcam phone / doomscroll watcher")
    parser.add_argument("--headless", action="store_true", help="Run without opening a preview window")
    parser.add_argument("--camera", type=int, default=config.CAMERA_INDEX, help="Camera device index")
    parser.add_argument("--sound", type=Path, default=config.SOUND_FILE, help="Optional local WAV file")
    parser.add_argument(
        "--test-beep",
        action="store_true",
        help="Play a test beep once and exit without starting the webcam detector.",
    )
    parser.add_argument(
        "--test-video",
        action="store_true",
        help="Play one random punishment video (or fall back to a beep) once and exit, "
        "without starting the webcam detector.",
    )
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="Run the interactive threshold calibration (writes calibration.json) and exit.",
    )
    return parser.parse_args()


def open_camera(camera_index: int) -> cv2.VideoCapture:
    capture = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, config.FRAME_WIDTH)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, config.FRAME_HEIGHT)
    return capture


def draw_status(frame: Any, status: str) -> None:
    label = _STATUS_LABELS.get(status, status)
    color = _STATUS_COLORS.get(status, (255, 255, 255))
    cv2.putText(frame, label, (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.75, color, 2)


def draw_phone_box(frame: Any, phone_box: tuple[int, int, int, int] | None) -> None:
    if phone_box is None:
        return
    x1, y1, x2, y2 = phone_box
    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 200, 255), 2)


def draw_debug_overlay(frame: Any, pitch_deg: float, eye_score: float, idle_seconds: float, progress_ratio: float) -> None:
    lines = [
        f"pitch: {pitch_deg:5.1f} deg",
        f"eyeLookDown: {eye_score:4.2f}",
        f"input idle: {idle_seconds:5.1f}s",
    ]
    y = 60
    for line in lines:
        cv2.putText(frame, line, (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
        y += 24

    bar_x, bar_y, bar_w, bar_h = 20, y + 6, 200, 14
    cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), (255, 255, 255), 1)
    filled = int(bar_w * max(0.0, min(1.0, progress_ratio)))
    if filled > 0:
        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + filled, bar_y + bar_h), (0, 200, 255), -1)


def run_calibration_mode(camera_index: int) -> int:
    capture = open_camera(camera_index)
    if not capture.isOpened():
        print(f"Could not open camera index {camera_index}. Check Windows camera permissions or try --camera 1.", file=sys.stderr)
        return 1
    try:
        calibration.run_calibration(capture)
        print(f"Calibration saved to {config.CALIBRATION_FILE}")
    finally:
        capture.release()
        cv2.destroyAllWindows()
    return 0


def run_test_video_mode(args: argparse.Namespace) -> int:
    player = PunishmentPlayer(videos_dir=config.PUNISHMENT_VIDEOS_DIR, sound_file=args.sound)
    player.trigger_blocking()
    print("Test video finished (or fell back to a beep).")
    return 0


def _watch_stop_flag(state: AppState, stop_flag_path: Path) -> None:
    while not state.stop_event.is_set():
        if stop_flag_path.is_file():
            state.stop_event.set()
            break
        state.stop_event.wait(0.5)


def run_monitor_mode(args: argparse.Namespace) -> int:
    existing_pid = process_control.get_running_pid(config.LOCK_FILE)
    if existing_pid is not None:
        print(
            f"Phone Watcher is already running (PID {existing_pid}). "
            "Use the desktop shortcut to stop it first.",
            file=sys.stderr,
        )
        return 1

    process_control.remove_file_if_exists(config.STOP_FLAG_FILE)
    process_control.write_lock(config.LOCK_FILE)

    state = AppState()
    stop_watcher = threading.Thread(
        target=_watch_stop_flag, args=(state, config.STOP_FLAG_FILE), daemon=True
    )
    stop_watcher.start()

    icon = tray.build_tray_icon(state, config.TRAY_ICON_FILE)
    icon.run_detached()

    capture = open_camera(args.camera)
    if not capture.isOpened():
        print(
            f"Could not open camera index {args.camera}. Check Windows camera permissions or try --camera 1.",
            file=sys.stderr,
        )
        state.stop_event.set()
        icon.stop()
        process_control.remove_file_if_exists(config.LOCK_FILE)
        return 1
    camera_open = True

    calibration_data = calibration.load_calibration()
    detector = WatcherDetector(calibration=calibration_data)
    state_machine = build_state_machine()
    punishment_player = PunishmentPlayer(videos_dir=config.PUNISHMENT_VIDEOS_DIR, sound_file=args.sound)

    headless = args.headless or config.HEADLESS
    paused = False  # keyboard 'p': lightweight "study mode" pause (state machine only)
    debug = False
    window_open = False
    frame_interval = 1.0 / config.LOOP_FPS_LIMIT if config.LOOP_FPS_LIMIT > 0 else 0.0

    print(f"=== Phone Watcher started {datetime.now().isoformat(timespec='seconds')} (PID {os.getpid()}) ===")
    print("Phone Watcher is running. Press 'q' to quit, 'p' to pause/resume, 'd' to toggle the debug overlay.")
    print("A tray icon is also available with Pause/Resume, Show/Hide preview, and Stop.")
    if headless:
        print("Headless mode enabled; stop with Ctrl+C or the tray icon.")
    if calibration_data is None:
        print("No calibration.json found; using default thresholds from config.py. Run 'python main.py --calibrate' to tune them.")

    exit_code = 0
    consecutive_camera_failures = 0
    max_consecutive_camera_failures = 60  # a real camera loss, not a one-off glitch

    try:
        while not state.stop_event.is_set():
            loop_start = time.monotonic()

            if state.tray_paused_event.is_set():
                if camera_open:
                    capture.release()
                    camera_open = False
                    if window_open and not headless:
                        cv2.destroyWindow(_WINDOW_NAME)
                        window_open = False
                    print("Paused from tray: camera released, CPU idle.")
                state.stop_event.wait(0.3)
                continue
            if not camera_open:
                capture = open_camera(args.camera)
                camera_open = True
                print("Resumed from tray.")

            # Everything below can occasionally hiccup (a dropped frame, a rare glitch in
            # the detection libraries, a display/session event confusing the preview
            # window). None of that should take the whole app down: log it and keep going.
            try:
                success, frame = capture.read()
                if not success:
                    consecutive_camera_failures += 1
                    print(
                        f"Could not read a frame from the camera "
                        f"({consecutive_camera_failures}/{max_consecutive_camera_failures}).",
                        file=sys.stderr,
                    )
                    if consecutive_camera_failures >= max_consecutive_camera_failures:
                        print("Camera appears to be lost; stopping.", file=sys.stderr)
                        break
                    time.sleep(0.1)
                    continue
                consecutive_camera_failures = 0

                if config.MIRROR_PREVIEW:
                    frame = cv2.flip(frame, 1)

                now = time.monotonic()
                result = detector.process(frame, now)
                idle_seconds = get_idle_seconds()

                decision = state_machine.update(
                    now=now,
                    phone_visible=result.phone_box is not None,
                    face_detected=result.face_detected,
                    looking_down=result.looking_down,
                    input_idle_seconds=idle_seconds,
                    paused=paused,
                )

                if decision.should_beep:
                    punishment_player.trigger()
                    if decision.reason == "phone":
                        print("Phone detected continuously; punishment triggered.")
                    elif decision.reason == "doomscroll":
                        print("Looking down with no keyboard/mouse activity; punishment triggered.")

                show_preview = not headless and not state.hide_preview_event.is_set()
                if show_preview:
                    draw_phone_box(frame, result.phone_box)
                    draw_status(frame, decision.status)
                    if debug:
                        draw_debug_overlay(
                            frame,
                            result.pitch_deg,
                            result.eye_look_down_score,
                            idle_seconds,
                            state_machine.progress_ratio(now),
                        )
                    cv2.imshow(_WINDOW_NAME, frame)
                    window_open = True
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord("q"):
                        break
                    if key == ord("p"):
                        paused = not paused
                        print("Paused." if paused else "Resumed.")
                    if key == ord("d"):
                        debug = not debug
                    try:
                        window_closed = cv2.getWindowProperty(_WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1
                    except cv2.error:
                        window_closed = False  # a transient HighGUI hiccup, not a real close
                    if window_closed:
                        break
                else:
                    if window_open and not headless:
                        cv2.destroyWindow(_WINDOW_NAME)
                        window_open = False
            except Exception:
                print("Unexpected error while processing a frame; continuing.", file=sys.stderr)
                traceback.print_exc()
                time.sleep(0.1)
                continue

            if frame_interval > 0:
                elapsed = time.monotonic() - loop_start
                remaining = frame_interval - elapsed
                if remaining > 0:
                    time.sleep(remaining)
    except KeyboardInterrupt:
        print("\nStopping Phone Watcher.")
    except (FileNotFoundError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        exit_code = 1
    finally:
        state.stop_event.set()
        try:
            icon.stop()
        except Exception:
            pass
        detector.close()
        if camera_open:
            capture.release()
        cv2.destroyAllWindows()
        process_control.remove_file_if_exists(config.LOCK_FILE)
        process_control.remove_file_if_exists(config.STOP_FLAG_FILE)
        print(f"=== Phone Watcher stopped {datetime.now().isoformat(timespec='seconds')} (exit_code={exit_code}) ===")

    # Everything that matters (camera, windows, lock/stop files) is already released above.
    # Skip Python's normal interpreter shutdown, which can otherwise stall for many seconds
    # on slow atexit/native teardown in mediapipe/ultralytics/numpy, so toggle.py's clean-stop
    # wait doesn't time out and fall back to a force-kill unnecessarily.
    os._exit(exit_code)


def main() -> int:
    args = parse_args()
    if args.test_beep:
        play_notification(args.sound)
        print("Test beep played.")
        return 0

    if args.test_video:
        return run_test_video_mode(args)

    if args.calibrate:
        return run_calibration_mode(args.camera)

    return run_monitor_mode(args)


if __name__ == "__main__":
    raise SystemExit(main())
