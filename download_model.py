"""Download the public MediaPipe Face Landmarker model used locally by the detector."""

from urllib.request import urlretrieve

from config import FACE_MODEL_PATH

FACE_MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"


def main() -> None:
    FACE_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading face landmark model to {FACE_MODEL_PATH} ...")
    urlretrieve(FACE_MODEL_URL, FACE_MODEL_PATH)
    print("Model download complete.")


if __name__ == "__main__":
    main()
