"""Punishment video playback: plays a random clip from punishment.videos/ on trigger,
with an automatic fallback to the plain beep if anything about that goes wrong.

Design notes:
  - Folder scanning uses pathlib.Path.suffix on each *file*, never string-splitting the
    directory itself, so a folder name containing a dot (e.g. "punishment.videos") is
    never mis-parsed as having an extension.
  - The actual playback happens in a *separate process* (video_player.py), waited on by a
    background thread here, so the camera/detection loop never blocks. It is a separate
    process rather than just a thread because Tkinter/Tcl may only be driven from a
    process's main thread -- doing it from a worker thread killed the whole app with a
    fatal "Tcl_AsyncDelete: async handler deleted by the wrong thread" panic after a few
    clips. Isolation also means a broken video can never crash the watcher.
  - `_vlc_module()` and `play_video_fn` are the two seams unit tests substitute to exercise
    the fallback logic without needing a real VLC install, a display, or real video files.
"""

import random
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable

import config
from notifier import play_notification

VIDEO_EXTENSIONS = config.PUNISHMENT_VIDEO_EXTENSIONS
VIDEO_PLAYER_SCRIPT = config.PROJECT_ROOT / "video_player.py"


def scan_videos(directory: Path, extensions: frozenset[str] = VIDEO_EXTENSIONS) -> list[Path]:
    """List playable video files directly inside `directory` (non-recursive).

    Re-scans on every call (by design: cheap for a handful of files, and it means videos
    added or removed between triggers show up immediately, with no restart needed).
    """
    if not directory.is_dir():
        return []
    videos = [p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in extensions]
    return sorted(videos)


def pick_random_video(
    videos: list[Path], exclude: Path | None, rng: random.Random | None = None
) -> Path | None:
    """Pick a random video, avoiding `exclude` (the previous pick) when more than one exists."""
    if not videos:
        return None
    rng = rng if rng is not None else random
    if exclude is not None and len(videos) > 1:
        candidates = [v for v in videos if v != exclude]
    else:
        candidates = list(videos)
    return rng.choice(candidates)


def _vlc_module() -> Any | None:
    """Import python-vlc, returning None (and logging why) if VLC isn't usable here."""
    try:
        import vlc

        return vlc
    except Exception as error:  # python-vlc raises various errors (ImportError, OSError,
        # ctypes load failures) depending on how libvlc.dll is missing/broken.
        print(f"[punishment] python-vlc / VLC is not available ({error}); falling back to beep alerts.", file=sys.stderr)
        return None


def _play_video_subprocess(
    video_path: Path,
    *,
    volume: int,
    portrait_height_ratio: float,
    landscape_width_ratio: float,
    max_duration_seconds: float,
) -> bool:
    """Play one video by running video_player.py as a separate process, and wait for it.

    Returns True if the player reported success (exit code 0), False otherwise, so the
    caller can try another file or fall back to the beep.
    """
    command = [
        sys.executable,
        "-u",
        str(VIDEO_PLAYER_SCRIPT),
        str(video_path),
        "--volume",
        str(volume),
        "--portrait-ratio",
        str(portrait_height_ratio),
        "--landscape-ratio",
        str(landscape_width_ratio),
        "--max-seconds",
        str(max_duration_seconds),
    ]
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    process = subprocess.Popen(command, cwd=str(config.PROJECT_ROOT), creationflags=creationflags)
    try:
        return process.wait(timeout=max_duration_seconds + 30) == 0
    except subprocess.TimeoutExpired:
        print(f"[punishment] {video_path} took too long; stopping the player.", file=sys.stderr)
        process.kill()
        return False


class PunishmentPlayer:
    """Plays a random punishment video on trigger, or falls back to a beep.

    Never lets a video-related error crash the caller: any failure is logged and the beep
    fallback plays instead. At most one video plays at a time -- a trigger received while
    one is already playing is silently ignored.
    """

    def __init__(
        self,
        videos_dir: Path | None = None,
        sound_file: Path | None = None,
        extensions: frozenset[str] = VIDEO_EXTENSIONS,
        volume: int | None = None,
        portrait_height_ratio: float | None = None,
        landscape_width_ratio: float | None = None,
        max_duration_seconds: float | None = None,
        play_video_fn: Callable[[Any, Path], bool] | None = None,
    ) -> None:
        self._videos_dir = videos_dir if videos_dir is not None else config.PUNISHMENT_VIDEOS_DIR
        self._sound_file = sound_file if sound_file is not None else config.SOUND_FILE
        self._extensions = extensions
        self._volume = volume if volume is not None else config.PUNISHMENT_VIDEO_VOLUME
        self._portrait_height_ratio = (
            portrait_height_ratio
            if portrait_height_ratio is not None
            else config.PUNISHMENT_VIDEO_PORTRAIT_HEIGHT_RATIO
        )
        self._landscape_width_ratio = (
            landscape_width_ratio
            if landscape_width_ratio is not None
            else config.PUNISHMENT_VIDEO_LANDSCAPE_WIDTH_RATIO
        )
        self._max_duration_seconds = (
            max_duration_seconds if max_duration_seconds is not None else config.PUNISHMENT_VIDEO_MAX_SECONDS
        )
        self._play_video_fn = play_video_fn
        self._lock = threading.Lock()
        self._is_playing = False
        self._last_played: Path | None = None

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    def trigger(self) -> None:
        """Non-blocking: start playback on a background thread, or no-op if one is playing."""
        if not self._claim():
            return
        threading.Thread(target=self._run, daemon=True).start()

    def trigger_blocking(self) -> None:
        """Blocking variant for --test-video: runs on the calling thread, returns when done."""
        if not self._claim():
            return
        self._run()

    def _claim(self) -> bool:
        with self._lock:
            if self._is_playing:
                return False
            self._is_playing = True
            return True

    def _run(self) -> None:
        try:
            self._play_or_fallback()
        finally:
            with self._lock:
                self._is_playing = False

    def _play_video(self, vlc_module: Any, video_path: Path) -> bool:
        if self._play_video_fn is not None:
            return self._play_video_fn(vlc_module, video_path)
        return _play_video_subprocess(
            video_path,
            volume=self._volume,
            portrait_height_ratio=self._portrait_height_ratio,
            landscape_width_ratio=self._landscape_width_ratio,
            max_duration_seconds=self._max_duration_seconds,
        )

    def _play_or_fallback(self) -> None:
        vlc_module = _vlc_module()
        if vlc_module is None:
            self._fallback_beep("VLC is unavailable")
            return

        videos = scan_videos(self._videos_dir, self._extensions)
        if not videos:
            self._fallback_beep(f"No videos found in {self._videos_dir}")
            return

        first_pick = pick_random_video(videos, exclude=self._last_played)
        order = [first_pick] + [v for v in videos if v != first_pick]

        for video_path in order:
            try:
                ok = self._play_video(vlc_module, video_path)
            except Exception as error:
                print(f"[punishment] error playing {video_path}: {error}", file=sys.stderr)
                ok = False
            if ok:
                self._last_played = video_path
                return
            print(f"[punishment] could not play {video_path}; trying another.", file=sys.stderr)

        self._fallback_beep("All punishment videos failed to play")

    def _fallback_beep(self, reason: str) -> None:
        print(f"[punishment] {reason}; falling back to beep.", file=sys.stderr)
        try:
            play_notification(self._sound_file)
        except (FileNotFoundError, RuntimeError) as error:
            print(f"[punishment] beep fallback also failed: {error}", file=sys.stderr)
