"""Generates icon.ico -- a simple phone-with-an-eye glyph -- for the tray icon and the
desktop shortcut. Run directly to (re)write icon.ico at the project root."""

from pathlib import Path

from PIL import Image, ImageDraw

import config


def build_icon_image(size: int = 256) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    margin_x = size * 0.27
    body = (margin_x, size * 0.07, size - margin_x, size * 0.93)
    outline_w = max(2, round(size * 0.016))
    draw.rounded_rectangle(
        body, radius=size * 0.09, fill=(32, 34, 40, 255), outline=(105, 110, 120, 255), width=outline_w
    )

    pad = size * 0.055
    screen = (body[0] + pad, body[1] + pad * 1.6, body[2] - pad, body[3] - pad * 1.6)
    draw.rounded_rectangle(screen, radius=size * 0.05, fill=(21, 101, 192, 255))

    notch_w, notch_h = size * 0.16, max(2.0, size * 0.02)
    cx = size / 2
    notch_y = body[1] + pad * 0.5
    draw.rounded_rectangle(
        (cx - notch_w / 2, notch_y, cx + notch_w / 2, notch_y + notch_h),
        radius=notch_h / 2,
        fill=(70, 74, 82, 255),
    )

    cy = size / 2
    eye_w, eye_h = size * 0.34, size * 0.19
    draw.ellipse(
        (cx - eye_w / 2, cy - eye_h / 2, cx + eye_w / 2, cy + eye_h / 2),
        fill=(255, 255, 255, 255),
        outline=(15, 15, 15, 255),
        width=max(2, round(size * 0.012)),
    )
    pupil_r = size * 0.065
    draw.ellipse((cx - pupil_r, cy - pupil_r, cx + pupil_r, cy + pupil_r), fill=(15, 15, 15, 255))
    highlight_r = size * 0.018
    hx, hy = cx - pupil_r * 0.35, cy - pupil_r * 0.35
    draw.ellipse((hx - highlight_r, hy - highlight_r, hx + highlight_r, hy + highlight_r), fill=(255, 255, 255, 255))

    return image


def save_icon(path: Path) -> None:
    image = build_icon_image(256)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def main() -> None:
    save_icon(config.TRAY_ICON_FILE)
    print(f"Icon saved to {config.TRAY_ICON_FILE}")


if __name__ == "__main__":
    main()
