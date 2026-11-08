"""Helper penyimpanan citra tahapan pengolahan untuk halaman debug."""
import os

import cv2

from config import UPLOAD_DIR

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
    """Ubah dict path menjadi daftar siap tampil di template."""
    items = []
    for name, path in saved.items():
        items.append(
            {
                "name": name,
                "label": STAGE_LABELS.get(name, name.replace("_", " ").title()),
                "path": path,
            }
        )
    return items
