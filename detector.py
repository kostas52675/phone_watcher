"""Signal extraction: a visible phone (YOLO) and head pose / gaze (MediaPipe Face Landmarker)."""

import math
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from config import (
    FACE_MODEL_PATH,
    DEFAULT_EYE_LOOK_DOWN_THRESHOLD,
    DEFAULT_PITCH_LOOKING_DOWN_THRESHOLD_DEG,
    GAZE_EMA_ALPHA,
    LOOKING_DOWN_MIN_DURATION_SECONDS,
    MIN_DETECTION_CONFIDENCE,
    MIN_TRACKING_CONFIDENCE,
    PHONE_CLASS_ID,
    PHONE_DETECTION_CONFIDENCE,
    PHONE_DETECTION_CONFIDENCE_LOW_ZONE,
    PHONE_DETECTION_FRAME_SKIP,
    PHONE_DETECTION_MODEL,
    PHONE_LOW_ZONE_HEIGHT_RATIO,
    PHONE_MIN_AREA_RATIO,
    PHONE_MIN_Y_RATIO,
)
from timing import SustainTimer

Box = tuple[int, int, int, int]


class PhoneDetector:
    """Runs YOLO on a subsample of frames and looks for a "cell phone" detection."""

    def __init__(self) -> None:
        try:
            from ultralytics import YOLO
        except ImportError as error:
            raise RuntimeError(
                "ultralytics is missing. Install dependencies with: pip install -r requirements.txt"
            ) from error

        self._model = YOLO(PHONE_DETECTION_MODEL)
        self._frame_index = 0
        self._last_box: Box | None = None

    def detect(self, frame: Any) -> Box | None:
        """Return the best "cell phone" box for this frame, reusing the last result on skipped frames."""
        run_this_frame = self._frame_index % PHONE_DETECTION_FRAME_SKIP == 0
        self._frame_index += 1
        if run_this_frame:
            self._last_box = self._run_yolo(frame)
        return self._last_box

    def _run_yolo(self, frame: Any) -> Box | None:
        height, width = frame.shape[:2]
        min_area = max(1, int(width * height * PHONE_MIN_AREA_RATIO))
        low_zone_y = height * (1 - PHONE_LOW_ZONE_HEIGHT_RATIO)
        lowest_confidence = min(PHONE_DETECTION_CONFIDENCE, PHONE_DETECTION_CONFIDENCE_LOW_ZONE)

        results = self._model(frame, verbose=False, conf=lowest_confidence, imgsz=640)

        best_box: Box | None = None
        best_score = -1.0
        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                cls_id = int(box.cls.item())
                if cls_id != PHONE_CLASS_ID:
                    continue
                score = float(box.conf.item())
                x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]

                required_confidence = (
                    PHONE_DETECTION_CONFIDENCE_LOW_ZONE if y2 >= low_zone_y else PHONE_DETECTION_CONFIDENCE
                )
                if score < required_confidence:
                    continue

                box_area = max(0, x2 - x1) * max(0, y2 - y1)
                if box_area < min_area:
                    continue
                if y2 < height * PHONE_MIN_Y_RATIO:
                    continue

                if score > best_score:
                    best_score = score
                    best_box = (x1, y1, x2, y2)

        return best_box


@dataclass
class FaceGazeResult:
    """State returned for each processed frame's head pose / gaze signal."""

    face_detected: bool
    pitch_deg: float  # smoothed head pitch, positive/negative meaning is calibration-dependent
    eye_look_down_score: float  # smoothed average of eyeLookDownLeft/Right blendshapes
    looking_down: bool  # thresholded AND blink-duration-filtered


# Landmark indices (same topology as MediaPipe Face Mesh) used for the solvePnP fallback
# head-pose estimate, with an approximate generic 3D face model in millimeters.
_SOLVEPNP_LANDMARK_INDICES = [1, 152, 33, 263, 61, 291]
_SOLVEPNP_MODEL_POINTS = np.array(
    [
        (0.0, 0.0, 0.0),  # nose tip
        (0.0, -63.6, -12.5),  # chin
        (43.3, 32.7, -26.0),  # right eye outer corner
        (-43.3, 32.7, -26.0),  # left eye outer corner
        (28.9, -28.9, -24.1),  # right mouth corner
        (-28.9, -28.9, -24.1),  # left mouth corner
    ],
    dtype=np.float64,
)


def _pitch_from_rotation_matrix(matrix: Any) -> float:
    """Extract a pitch angle (degrees) from a 3x3 or 4x4 rotation matrix."""
    values = np.asarray(matrix, dtype=np.float64).reshape(-1)
    rotation = values.reshape(4, 4)[:3, :3] if values.size >= 16 else values.reshape(3, 3)

    sy = math.sqrt(rotation[0, 0] ** 2 + rotation[1, 0] ** 2)
    if sy < 1e-6:
        pitch = math.atan2(-rotation[1, 2], rotation[1, 1])
    else:
        pitch = math.atan2(rotation[2, 1], rotation[2, 2])
    return math.degrees(pitch)


def _pitch_from_solvepnp(landmarks: Any, frame_shape: tuple[int, ...]) -> float:
    """Fallback head-pose pitch estimate when a transformation matrix isn't available."""
    height, width = frame_shape[:2]
    try:
        image_points = np.array(
            [(landmarks[i].x * width, landmarks[i].y * height) for i in _SOLVEPNP_LANDMARK_INDICES],
            dtype=np.float64,
        )
    except IndexError:
        return 0.0

    focal_length = float(width)
    camera_matrix = np.array(
        [[focal_length, 0, width / 2], [0, focal_length, height / 2], [0, 0, 1]],
        dtype=np.float64,
    )
    dist_coeffs = np.zeros((4, 1))

    success, rotation_vector, _ = cv2.solvePnP(
        _SOLVEPNP_MODEL_POINTS,
        image_points,
        camera_matrix,
        dist_coeffs,
        flags=cv2.SOLVEPNP_ITERATIVE,
    )
    if not success:
        return 0.0

    rotation_matrix, _ = cv2.Rodrigues(rotation_vector)
    return _pitch_from_rotation_matrix(rotation_matrix)


def _extract_eye_look_down(result: Any) -> float:
    if not result.face_blendshapes:
        return 0.0
    scores = {category.category_name: category.score for category in result.face_blendshapes[0]}
    left = scores.get("eyeLookDownLeft", 0.0)
    right = scores.get("eyeLookDownRight", 0.0)
    return (left + right) / 2


class FaceGazeDetector:
    """Head pose (pitch) + gaze-down (eye blendshapes) signal, smoothed and blink-filtered."""

    def __init__(self, calibration: dict | None = None) -> None:
        try:
            import mediapipe as mp
            from mediapipe.tasks.python import vision as mp_vision
            from mediapipe.tasks.python.core.base_options import BaseOptions
        except ImportError as error:
            raise RuntimeError(
                "mediapipe is missing. Install dependencies with: pip install -r requirements.txt"
            ) from error

        if not FACE_MODEL_PATH.is_file():
            raise FileNotFoundError(
                f"Missing face landmark model at {FACE_MODEL_PATH}. Run 'python download_model.py' first."
            )

        self._mp = mp
        options = mp_vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(FACE_MODEL_PATH)),
            running_mode=mp_vision.RunningMode.VIDEO,
            num_faces=1,
            min_face_detection_confidence=MIN_DETECTION_CONFIDENCE,
            min_tracking_confidence=MIN_TRACKING_CONFIDENCE,
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=True,
        )
        self._landmarker = mp_vision.FaceLandmarker.create_from_options(options)

        calibration = calibration or {}
        self._pitch_threshold = calibration.get(
            "pitch_looking_down_threshold_deg", DEFAULT_PITCH_LOOKING_DOWN_THRESHOLD_DEG
        )
        self._pitch_direction = calibration.get("pitch_direction", 1.0)
        self._eye_threshold = calibration.get("eye_look_down_threshold", DEFAULT_EYE_LOOK_DOWN_THRESHOLD)
        self._eye_direction = calibration.get("eye_direction", 1.0)

        self._pitch_ema: float | None = None
        self._eye_ema: float | None = None
        self._down_timer = SustainTimer(min_duration_seconds=LOOKING_DOWN_MIN_DURATION_SECONDS)
        self._last_timestamp_ms = -1

    def process(self, frame: Any, now: float) -> FaceGazeResult:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)

        # detect_for_video requires a strictly increasing timestamp per call.
        timestamp_ms = max(int(now * 1000), self._last_timestamp_ms + 1)
        self._last_timestamp_ms = timestamp_ms
        result = self._landmarker.detect_for_video(mp_image, timestamp_ms)

        if not result.face_landmarks:
            self._pitch_ema = None
            self._eye_ema = None
            self._down_timer.reset()
            return FaceGazeResult(face_detected=False, pitch_deg=0.0, eye_look_down_score=0.0, looking_down=False)

        if result.facial_transformation_matrixes:
            pitch_deg = _pitch_from_rotation_matrix(result.facial_transformation_matrixes[0])
        else:
            pitch_deg = _pitch_from_solvepnp(result.face_landmarks[0], frame.shape)
        eye_score = _extract_eye_look_down(result)

        self._pitch_ema = pitch_deg if self._pitch_ema is None else (
            GAZE_EMA_ALPHA * pitch_deg + (1 - GAZE_EMA_ALPHA) * self._pitch_ema
        )
        self._eye_ema = eye_score if self._eye_ema is None else (
            GAZE_EMA_ALPHA * eye_score + (1 - GAZE_EMA_ALPHA) * self._eye_ema
        )

        raw_down = (self._pitch_ema - self._pitch_threshold) * self._pitch_direction > 0 or (
            self._eye_ema - self._eye_threshold
        ) * self._eye_direction > 0
        looking_down = self._down_timer.update(raw_down, now)

        return FaceGazeResult(
            face_detected=True,
            pitch_deg=self._pitch_ema,
            eye_look_down_score=self._eye_ema,
            looking_down=looking_down,
        )

    def close(self) -> None:
        self._landmarker.close()


@dataclass
class DetectionResult:
    """Combined per-frame signals used by the state machine and the preview overlay."""

    phone_box: Box | None
    face_detected: bool
    pitch_deg: float
    eye_look_down_score: float
    looking_down: bool


class WatcherDetector:
    """Combines the phone detector and the face/gaze detector into one per-frame call."""

    def __init__(self, calibration: dict | None = None) -> None:
        self._phone_detector = PhoneDetector()
        self._face_detector = FaceGazeDetector(calibration=calibration)

    def process(self, frame: Any, now: float) -> DetectionResult:
        phone_box = self._phone_detector.detect(frame)
        gaze = self._face_detector.process(frame, now)
        return DetectionResult(
            phone_box=phone_box,
            face_detected=gaze.face_detected,
            pitch_deg=gaze.pitch_deg,
            eye_look_down_score=gaze.eye_look_down_score,
            looking_down=gaze.looking_down,
        )

    def close(self) -> None:
        self._face_detector.close()
