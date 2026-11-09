"""Buat favicon dan ikon aplikasi dari logo proyek.

Jalankan dari mana saja:
    python tools/make_icons.py
"""
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent.parent
SRC = BASE_DIR / "static" / "img" / "logo-projek.jpeg"
OUT_DIR = BASE_DIR / "static" / "img"
ICO_PATH = BASE_DIR / "static" / "favicon.ico"

PADDING = 0.04


def content_box(rgb):
    """Batas area logo, mengabaikan latar putih di sekelilingnya."""
    background = rgb[0, 0].astype(int)
    difference = np.abs(rgb.astype(int) - background).sum(axis=2)
    ys, xs = np.where(difference > 18)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def build_canvas(image, box, background=(255, 255, 255)):
    """Potong logo, beri sedikit ruang, lalu tempel di kanvas persegi."""
    cropped = image.crop(box)
    side = max(cropped.size)
    padding = int(round(side * PADDING))
    canvas = Image.new(image.mode, (side + padding * 2, side + padding * 2), background)
    canvas.paste(
        cropped,
        ((canvas.width - cropped.width) // 2, (canvas.height - cropped.height) // 2),
        cropped if cropped.mode == "RGBA" else None,
    )
    return canvas


def build_transparent(image, box):
    """Versi transparan untuk logo kecil di navbar/login."""
    rgb = np.array(image)
    near_white = np.all(rgb >= 238, axis=2).astype(np.uint8) * 255
    mask = np.zeros((rgb.shape[0] + 2, rgb.shape[1] + 2), np.uint8)
    cv2.floodFill(near_white, mask, (0, 0), 128)
    alpha = np.where(near_white == 128, 0, 255).astype(np.uint8)
    rgba = Image.fromarray(np.dstack([rgb, alpha]), "RGBA")
    return build_canvas(rgba, box, (255, 255, 255, 0))


def main():
    if not SRC.exists():
        raise SystemExit(f"Logo tidak ditemukan: {SRC}")

    source = Image.open(SRC).convert("RGB")
    box = content_box(np.array(source))
    opaque = build_canvas(source, box)
    transparent = build_transparent(source, box)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, size in {
        "logo-512.png": 512,
        "logo-192.png": 192,
        "apple-touch-icon.png": 180,
        "favicon-32.png": 32,
        "favicon-16.png": 16,
    }.items():
        opaque.resize((size, size), Image.Resampling.LANCZOS).save(
            OUT_DIR / name, optimize=True
        )
        print("tulis", OUT_DIR / name)

    opaque.resize((256, 256), Image.Resampling.LANCZOS).save(
        ICO_PATH, sizes=[(16, 16), (32, 32), (48, 48), (64, 64)]
    )
    print("tulis", ICO_PATH)

    transparent.resize((128, 128), Image.Resampling.LANCZOS).save(
        OUT_DIR / "logo-mark.png", optimize=True
    )
    print("tulis", OUT_DIR / "logo-mark.png")


if __name__ == "__main__":
    main()
