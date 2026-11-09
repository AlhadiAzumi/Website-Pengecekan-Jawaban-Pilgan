"""Konfigurasi global aplikasi."""
import os
import secrets

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Di Render, arahkan PILGAN_DATA_DIR ke persistent disk (mis. /var/data).
DATA_DIR = os.environ.get("PILGAN_DATA_DIR", BASE_DIR)
INSTANCE_DIR = os.path.join(DATA_DIR, "instance")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
TEMPLATE_UPLOAD_DIR = os.path.join(UPLOAD_DIR, "templates")
SCAN_UPLOAD_DIR = os.path.join(UPLOAD_DIR, "scans")
DEBUG_UPLOAD_DIR = os.path.join(UPLOAD_DIR, "debug")
GENERATED_DIR = os.path.join(UPLOAD_DIR, "generated")

DATABASE_PATH = os.path.join(INSTANCE_DIR, "pilgan.db")

# Default SQLite. Untuk PostgreSQL, isi DATABASE_URL di environment.
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DATABASE_PATH}")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "bmp"}
ALLOWED_EXCEL_EXTENSIONS = {"xlsx", "xls"}

MAX_CONTENT_LENGTH = 32 * 1024 * 1024
MAX_BATCH_FILES = 50

# Ukuran acuan internal untuk penyelarasan lembar jawaban.
CANONICAL_LONG_SIDE = 1600

DEFAULT_SETTINGS = {
    "fill_ratio": 0.40,
    "threshold_method": "otsu",
    "adaptive_block_size": 31,
    "adaptive_c": 15,
    "morph_kernel": 3,
    "detect_threshold": 0,
    "min_area": 120,
    "max_area": 4000,
    "circularity": 0.60,
    "blur_threshold": 45.0,
}


def ensure_directories():
    for path in (
        INSTANCE_DIR,
        UPLOAD_DIR,
        TEMPLATE_UPLOAD_DIR,
        SCAN_UPLOAD_DIR,
        DEBUG_UPLOAD_DIR,
        GENERATED_DIR,
    ):
        os.makedirs(path, exist_ok=True)


def load_secret_key():
    """Pakai SECRET_KEY dari env, atau buat kunci lokal yang persisten."""
    env_key = os.environ.get("SECRET_KEY", "").strip()
    if env_key:
        return env_key

    path = os.path.join(INSTANCE_DIR, "secret_key")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            saved = handle.read().strip()
        if len(saved) >= 32:
            return saved
    except OSError:
        pass

    key = secrets.token_hex(32)
    try:
        os.makedirs(INSTANCE_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(key)
    except OSError:
        pass
    return key
