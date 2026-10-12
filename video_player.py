"""Standalone player that shows ONE punishment video and then exits.

This runs as its own process on purpose. Tkinter/Tcl may only be driven from a process's
main thread: playing videos from the watcher's background thread crashed the whole app
with a fatal "Tcl_AsyncDelete: async handler deleted by the wrong thread" panic after a
couple of clips. Running here, on this process's main thread, is legal -- and the process
isolation also means a broken clip or a VLC hiccup can never take the watcher down.

Exit codes: 0 = played, 1 = playback failed, 2 = VLC unavailable.
"""

import argparse
import sys
import threading
import tkinter as tk
import traceback
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Play one punishment video, then exit.")
    parser.add_argument("video", type=Path, help="Video file to play")
    parser.add_argument("--volume", type=int, default=100, help="Playback volume, 0-100")
    parser.add_argument("--portrait-ratio", type=float, default=0.8, help="Window height / screen height for portrait clips")
    parser.add_argument("--landscape-ratio", type=float, default=0.6, help="Window width / screen width for landscape clips")
    parser.add_argument("--max-seconds", type=float, default=120.0, help="Failsafe cap on playback length")
    return parser.parse_args()


def compute_window_geometry(
    video_size: tuple[int, int] | None,
    screen_w: int,
    screen_h: int,
    portrait_height_ratio: float,
    landscape_width_ratio: float,
) -> tuple[int, int, int, int]:
    """Return (width, height, x, y) for a centered window that preserves aspect ratio."""
    if video_size is None:
        video_w, video_h = 9, 16  # unknown size: assume portrait, matching the user's own clips
    else:
        video_w, video_h = video_size

    if video_h >= video_w:  # portrait or square
        win_h = int(screen_h * portrait_height_ratio)
        win_w = max(1, int(win_h * video_w / video_h))
    else:  # landscape
        win_w = int(screen_w * landscape_width_ratio)
        win_h = max(1, int(win_w * video_h / video_w))

    win_w = max(1, min(win_w, screen_w))
    win_h = max(1, min(win_h, screen_h))
    x = (screen_w - win_w) // 2
    y = (screen_h - win_h) // 2
    return win_w, win_h, x, y


def _get_video_size(vlc_module: Any, media: Any) -> tuple[int, int] | None:
    try:
        media.parse()
        tracks = media.tracks_get()
    except Exception:
        return None
    if not tracks:
        return None
    for track in tracks:
        try:
            if track.type != vlc_module.TrackType.video:
                continue
            video = track.video.contents
            width, height = int(video.width), int(video.height)
        except Exception:
            continue
        if width > 0 and height > 0:
            return width, height
    return None


def play(
    vlc_module: Any,
    video_path: Path,
    *,
    volume: int,
    portrait_height_ratio: float,
    landscape_width_ratio: float,
    max_duration_seconds: float,
) -> bool:
    """Play the video always-on-top, centered, no controls; close automatically when it ends."""
    instance = vlc_module.Instance("--quiet", "--no-video-title-show")
    media = instance.media_new(str(video_path))
    video_size = _get_video_size(vlc_module, media)
    try:
        duration_ms = media.get_duration()
    except Exception:
        duration_ms = -1

    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.configure(bg="black")
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    win_w, win_h, x, y = compute_window_geometry(
        video_size, screen_w, screen_h, portrait_height_ratio, landscape_width_ratio
    )
    root.geometry(f"{win_w}x{win_h}+{x}+{y}")
    root.update_idletasks()

    player = instance.media_player_new()
    player.set_media(media)
    player.audio_set_volume(max(0, min(100, volume)))
    player.set_hwnd(root.winfo_id())

    finished = threading.Event()
    failed = threading.Event()

    def on_end(_event):
        finished.set()

    def on_error(_event):
        failed.set()
        finished.set()

    events = player.event_manager()
    events.event_attach(vlc_module.EventType.MediaPlayerEndReached, on_end)
    events.event_attach(vlc_module.EventType.MediaPlayerEncounteredError, on_error)

    def close_when_done():
        if finished.is_set():
            try:
                root.destroy()
            except tk.TclError:
                pass
            return
        root.after(100, close_when_done)

    if player.play() == -1:
        try:
            root.destroy()
        except tk.TclError:
            pass
        return False

    # Safety net in case MediaPlayerEndReached never fires (unusual container/codec).
    fallback_seconds = (duration_ms / 1000.0) if duration_ms and duration_ms > 0 else max_duration_seconds
    root.after(100, close_when_done)
    root.after(int(fallback_seconds * 1000) + 5000, finished.set)

    root.mainloop()

    try:
        player.stop()
        events.event_detach(vlc_module.EventType.MediaPlayerEndReached)
        events.event_detach(vlc_module.EventType.MediaPlayerEncounteredError)
        player.release()
        media.release()
        instance.release()
    except Exception:
        pass

    return not failed.is_set()


def main() -> int:
    args = parse_args()
    if not args.video.is_file():
        print(f"[video_player] file not found: {args.video}", file=sys.stderr)
        return 1

    try:
        import vlc
    except Exception as error:  # ImportError, OSError, ctypes load failures...
        print(f"[video_player] VLC is not available ({error}).", file=sys.stderr)
        return 2

    try:
        played = play(
            vlc,
            args.video,
            volume=args.volume,
            portrait_height_ratio=args.portrait_ratio,
            landscape_width_ratio=args.landscape_ratio,
            max_duration_seconds=args.max_seconds,
        )
    except Exception:
        print(f"[video_player] error while playing {args.video}:", file=sys.stderr)
        traceback.print_exc()
        return 1

    return 0 if played else 1


if __name__ == "__main__":
    raise SystemExit(main())
