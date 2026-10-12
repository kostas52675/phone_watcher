"""Local sound notification helpers."""

import sys
import time
from pathlib import Path


def play_notification(sound_file: Path | None, count: int = 1, interval_ms: int = 120) -> None:
    """Play a local WAV file or system beep repeated a number of times."""
    if count <= 0:
        return

    def emit_once() -> None:
        if sound_file is None:
            if sys.platform == "win32":
                import winsound

                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            else:
                print("\a", end="", flush=True)
            return

        if not sound_file.is_file():
            raise FileNotFoundError(f"Sound file was not found: {sound_file}")

        try:
            import simpleaudio
        except ImportError as error:
            raise RuntimeError(
                "simpleaudio is missing. Install dependencies with: pip install -r requirements.txt"
            ) from error
        simpleaudio.WaveObject.from_wave_file(str(sound_file)).play()

    for index in range(count):
        emit_once()
        if index < count - 1:
            time.sleep(interval_ms / 1000)
