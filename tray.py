"""System tray icon: Pause/Resume, Show/Hide preview, Stop. Runs in-process alongside the
detection loop, wired to it purely through the shared AppState events."""

import sys
from pathlib import Path

import pystray
from PIL import Image

from app_state import AppState


def _load_icon_image(icon_path: Path) -> Image.Image:
    if icon_path.is_file():
        try:
            return Image.open(icon_path).convert("RGBA")
        except Exception as error:
            print(f"[tray] could not load icon {icon_path} ({error}); using a generated fallback.", file=sys.stderr)
    from make_icon import build_icon_image

    return build_icon_image()


def build_tray_icon(state: AppState, icon_path: Path) -> pystray.Icon:
    image = _load_icon_image(icon_path)

    def on_pause_resume(icon, item):
        if state.tray_paused_event.is_set():
            state.tray_paused_event.clear()
        else:
            state.tray_paused_event.set()

    def on_show_hide(icon, item):
        if state.hide_preview_event.is_set():
            state.hide_preview_event.clear()
        else:
            state.hide_preview_event.set()

    def on_stop(icon, item):
        state.stop_event.set()
        icon.stop()

    def pause_text(item):
        return "Resume" if state.tray_paused_event.is_set() else "Pause"

    def show_text(item):
        return "Show preview" if state.hide_preview_event.is_set() else "Hide preview"

    menu = pystray.Menu(
        pystray.MenuItem(pause_text, on_pause_resume),
        pystray.MenuItem(show_text, on_show_hide),
        pystray.MenuItem("Stop", on_stop),
    )
    return pystray.Icon("phone_watcher", image, "Phone Watcher", menu)
