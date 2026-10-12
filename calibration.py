"""Interactive on-screen calibration for head-pitch / gaze-down thresholds.

Only aggregate pitch and eye-gaze numbers are written to calibration.json.
No video frames or images are ever saved to disk.
"""

import json
import time
from typing import Any

import cv2

import config
from detector import FaceGazeDetector

# OpenCV's built-in font cannot render Greek glyphs, so the on-screen label is a short
# ASCII phase name; the full instruction is printed to the console in Greek.
_PHASES = [
    ("screen", "1/3  LOOK AT SCREEN", "Fasi 1/3: Koita tin othoni kanonika."),
    ("keyboard", "2/3  LOOK AT KEYBOARD", "Fasi 2/3: Koita to plktrologio kai plktrologise."),
    ("phone", "3/3  LOOK AT PHONE (LOW)", "Fasi 3/3: Koita to kinito sou san na kaneis scroll (krata to xamila)."),
]


def run_calibration(capture: Any, phase_seconds: float | None = None) -> dict:
    """Run the 3-phase guided calibration and write calibration.json. Returns the saved data."""
    phase_seconds = phase_seconds if phase_seconds is not None else config.CALIBRATION_PHASE_SECONDS
    face_detector = FaceGazeDetector()
    samples: dict[str, dict[str, float]] = {}

    try:
        for key, on_screen_label, console_message in _PHASES:
            print(console_message)
            pitches: list[float] = []
            eye_scores: list[float] = []
            phase_start = time.monotonic()

            while True:
                now = time.monotonic()
                elapsed = now - phase_start
                if elapsed >= phase_seconds:
                    break

                success, frame = capture.read()
                if not success:
                    continue
                if config.MIRROR_PREVIEW:
                    frame = cv2.flip(frame, 1)

                gaze = face_detector.process(frame, now)
                if gaze.face_detected:
                    pitches.append(gaze.pitch_deg)
                    eye_scores.append(gaze.eye_look_down_score)

                _draw_phase_overlay(frame, on_screen_label, max(0.0, phase_seconds - elapsed))
                cv2.imshow("Phone Watcher - Calibration", frame)
                cv2.waitKey(1)

            samples[key] = {
                "pitch": sum(pitches) / len(pitches) if pitches else 0.0,
                "eye_look_down": sum(eye_scores) / len(eye_scores) if eye_scores else 0.0,
            }
    finally:
        face_detector.close()
        cv2.destroyWindow("Phone Watcher - Calibration")

    calibration_data = _build_thresholds(samples)
    config.CALIBRATION_FILE.write_text(json.dumps(calibration_data, indent=2), encoding="utf-8")
    return calibration_data


def _build_thresholds(samples: dict) -> dict:
    screen = samples.get("screen", {"pitch": 0.0, "eye_look_down": 0.0})
    phone = samples.get("phone", {"pitch": 0.0, "eye_look_down": 0.0})

    pitch_threshold = (screen["pitch"] + phone["pitch"]) / 2
    eye_threshold = (screen["eye_look_down"] + phone["eye_look_down"]) / 2
    # Store which direction means "looking down" so the raw sign convention of the
    # rotation-matrix pitch (which can vary) doesn't need to be hardcoded elsewhere.
    pitch_direction = 1.0 if phone["pitch"] >= screen["pitch"] else -1.0
    eye_direction = 1.0 if phone["eye_look_down"] >= screen["eye_look_down"] else -1.0

    return {
        "pitch_looking_down_threshold_deg": pitch_threshold,
        "pitch_direction": pitch_direction,
        "eye_look_down_threshold": eye_threshold,
        "eye_direction": eye_direction,
        "samples": samples,
    }


def load_calibration() -> dict | None:
    """Load calibration.json if it exists, else None so callers fall back to config defaults."""
    if not config.CALIBRATION_FILE.is_file():
        return None
    try:
        return json.loads(config.CALIBRATION_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _draw_phase_overlay(frame: Any, label: str, remaining_seconds: float) -> None:
    cv2.putText(frame, "CALIBRATION", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(frame, label, (20, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 255), 2)
    cv2.putText(frame, f"{remaining_seconds:0.1f}s", (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
