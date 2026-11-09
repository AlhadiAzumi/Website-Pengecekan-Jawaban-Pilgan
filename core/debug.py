"""Helper penyimpanan citra tahapan pengolahan untuk halaman debug."""
import os

import cv2

from config import UPLOAD_DIR
from core.alignment import preprocess_debug

STAGE_LABELS = {
    "1_original": "1. Citra Asli",
    "2_grayscale": "2. Grayscale",
    "3_blur": "3. Gaussian Blur",
    "4_canny": "4. Deteksi Tepi",
    "5_kontur": "5. Kontur Kertas",
    "5_marker": "5. Marker Sudut",
    "5_orb": "5. ORB Matching",
    "6_aligned": "6. Hasil Penyelarasan",
    "7_threshold": "7. Threshold",
    "8_morphology": "8. Morfologi",
    "9_deteksi": "9. Hasil Deteksi",
}

# Jika beberapa varian tahap 5 muncul, tampilkan dalam urutan metode yang dicoba.
STAGE_PRIORITY = {
    "5_kontur": 0,
    "5_marker": 1,
    "5_orb": 2,
}


KIND_SECTIONS = {
    "template": [
        ("2_grayscale", "grayscale"),
        ("7_threshold", "threshold"),
        ("9_deteksi", "candidates"),
    ],
    "scan": [
        ("1_original", "original"),
        ("2_grayscale", "gray"),
        ("7_threshold", "binary"),
        ("8_morphology", "morph"),
        ("9_deteksi", "annotated"),
    ],
}


def relative_path(absolute_path):
    """Ubah path absolut menjadi path relatif terhadap folder uploads."""
    if not absolute_path:
        return ""
    return os.path.relpath(absolute_path, UPLOAD_DIR).replace("\\", "/")


def save_debug_image(folder, name, image):
    """Simpan satu citra debug dan kembalikan path relatifnya."""
    if image is None:
        return ""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{name}.jpg")
    if not cv2.imwrite(path, image):
        return ""
    return relative_path(path)


def save_debug_set(folder, images):
    """Simpan sekumpulan citra debug dari dict {nama: citra}."""
    saved = {}
    for name, image in images.items():
        path = save_debug_image(folder, name, image)
        if path:
            saved[name] = path
    return saved


def debug_items(saved):
    """Ubah dict path menjadi daftar siap tampil, terurut sesuai nomor tahap."""
    items = []
    for name in sorted(saved, key=_stage_key):
        path = saved[name]
        items.append(
            {
                "name": name,
                "label": STAGE_LABELS.get(name, name.replace("_", " ").title()),
                "path": path,
            }
        )
    return items


def _stage_key(name):
    """Kunci urutan: nomor tahap, varian tahap 5, lalu nama."""
    prefix = name.split("_", 1)[0]
    try:
        number = int(prefix)
    except ValueError:
        number = 999
    return (number, STAGE_PRIORITY.get(name, 0), name)


def complete_debug_stages(saved):
    """Lengkapi tahap blur/tepi pada hasil scan lama yang belum menyimpannya."""
    if not saved:
        return saved

    updated = dict(saved)

    def absolute(relative):
        return os.path.join(UPLOAD_DIR, relative.replace("/", os.sep))

    folder = None
    if "2_grayscale" in saved and "3_blur" not in saved:
        gray_path = absolute(saved["2_grayscale"])
        gray = cv2.imread(gray_path, cv2.IMREAD_GRAYSCALE)
        if gray is not None:
            folder = os.path.dirname(gray_path)
            blur = cv2.GaussianBlur(gray, (5, 5), 0)
            path = save_debug_image(folder, "3_blur", blur)
            if path:
                updated["3_blur"] = path

    if "1_original" in saved and "4_canny" not in saved:
        original_path = absolute(saved["1_original"])
        original = cv2.imread(original_path)
        if original is not None:
            folder = folder or os.path.dirname(original_path)
            _, _, edges = preprocess_debug(original)
            path = save_debug_image(folder, "4_canny", edges)
            if path:
                updated["4_canny"] = path

    return updated

