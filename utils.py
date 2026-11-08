"""Fungsi bantu upload, path, dan validasi berkas."""
import os
import uuid

import cv2
import numpy as np

from config import ALLOWED_IMAGE_EXTENSIONS, TEMPLATE_UPLOAD_DIR, UPLOAD_DIR


def allowed_image(filename):
    if "." not in filename:
        return False
    extension = filename.rsplit(".", 1)[1].lower()
    return extension in ALLOWED_IMAGE_EXTENSIONS


def extension_of(filename):
    return filename.rsplit(".", 1)[1].lower() if "." in filename else ""


def abs_upload(relative_path):
    """Ubah path relatif (disimpan di DB) menjadi path absolut."""
    if not relative_path:
        return ""
    if os.path.isabs(relative_path):
        return relative_path
    return os.path.join(UPLOAD_DIR, relative_path.replace("/", os.sep))


def rel_upload(absolute_path):
    return os.path.relpath(absolute_path, UPLOAD_DIR).replace("\\", "/")


def safe_upload_path(relative_path):
    """Pastikan path tetap berada di dalam folder uploads."""
    absolute = os.path.abspath(abs_upload(relative_path))
    root = os.path.abspath(UPLOAD_DIR)
    if not absolute.startswith(root + os.sep) and absolute != root:
        return ""
    return absolute


def save_upload_image(file_storage, prefix="img", subdir=None):
    """Simpan file upload sebagai citra. Kembalikan (abs_path, rel_path, image)."""
    if file_storage is None or not file_storage.filename:
        raise ValueError("File gambar belum dipilih.")
    if not allowed_image(file_storage.filename):
        raise ValueError(
            "Format gambar tidak didukung. Gunakan PNG, JPG, JPEG, WEBP, atau BMP."
        )
    data = file_storage.read()
    if not data:
        raise ValueError("File gambar kosong.")
    array = np.frombuffer(data, np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(
            "Gambar tidak dapat dibaca. Pastikan file tidak rusak dan berformat gambar."
        )
    extension = extension_of(file_storage.filename)
    folder = subdir or TEMPLATE_UPLOAD_DIR
    os.makedirs(folder, exist_ok=True)
    filename = f"{prefix}_{uuid.uuid4().hex}.{extension}"
    path = os.path.join(folder, filename)
    with open(path, "wb") as handle:
        handle.write(data)
    return path, rel_upload(path), image


def read_image_path(path):
    if not path:
        return None
    image = cv2.imread(path)
    return image


def new_id():
    return uuid.uuid4().hex
