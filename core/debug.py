"""Helper penyimpanan citra tahapan pengolahan untuk halaman debug."""
import os

import cv2

from config import UPLOAD_DIR
from core.alignment import detect_paper_corners, preprocess_debug

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


def debug_items_in_folder(folder):
    """Baca citra tahap 1-9 yang sudah tersimpan di sebuah folder debug."""
    if not folder or not os.path.isdir(folder):
        return []
    saved = {}
    for filename in os.listdir(folder):
        stem, extension = os.path.splitext(filename)
        if extension.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        if stem not in STAGE_LABELS:
            continue
        saved[stem] = relative_path(os.path.join(folder, filename))
    return debug_items(saved)


def build_template_stages(source_image, reference, detection, alignment_steps=None):
    """Susun citra tahap 1-9 untuk proses pembuatan templat kosong."""
    debug = (detection or {}).get("debug", {})
    stages = {}

    if source_image is not None:
        gray, blur, edges = preprocess_debug(source_image)
        stages["1_original"] = source_image
        stages["2_grayscale"] = gray
        stages["3_blur"] = blur
        stages["4_canny"] = edges

    if reference is not None:
        stages.setdefault("2_grayscale", debug.get("grayscale"))
        stages.setdefault("3_blur", debug.get("blur"))
        if "4_canny" not in stages:
            stages["4_canny"] = preprocess_debug(reference)[2]
        stages["6_aligned"] = reference

    if "1_original" not in stages:
        fallback = reference if reference is not None else debug.get("grayscale")
        if fallback is not None:
            stages["1_original"] = fallback

    outline = (alignment_steps or {}).get("outline")
    if outline is None and source_image is not None:
        _, paper_debug = detect_paper_corners(source_image)
        outline = paper_debug.get("outline")
    stages["5_kontur"] = outline if outline is not None else stages.get("4_canny")

    threshold = debug.get("binary")
    if threshold is None:
        threshold = debug.get("threshold")
    stages["7_threshold"] = threshold
    stages["8_morphology"] = debug.get("threshold")
    if "7_threshold" not in stages:
        stages["7_threshold"] = stages.get("8_morphology")

    preview = (detection or {}).get("preview")
    if preview is not None:
        stages["9_deteksi"] = preview

    return {name: image for name, image in stages.items() if image is not None}


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

