"""Akun tunggal aplikasi: penyimpanan hash password dan validasi login."""
import hmac
import re

from werkzeug.security import check_password_hash, generate_password_hash

from models import AppSetting, db

USERNAME_KEY = "auth_username"
PASSWORD_KEY = "auth_password_hash"
MIN_PASSWORD_LENGTH = 6
MAX_PASSWORD_LENGTH = 128
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{3,40}$")


def get_account():
    """Ambil akun aktif, atau None bila belum pernah dibuat."""
    rows = {
        row.key: row.value
        for row in AppSetting.query.filter(
            AppSetting.key.in_([USERNAME_KEY, PASSWORD_KEY])
        ).all()
    }
    username = (rows.get(USERNAME_KEY) or "").strip()
    password_hash = rows.get(PASSWORD_KEY) or ""
    if not username or not password_hash:
        return None
    return {"username": username, "password_hash": password_hash}


def validate_username(username):
    """Kembalikan pesan kesalahan, atau None jika username valid."""
    if not username:
        return "Username wajib diisi."
    if not USERNAME_PATTERN.match(username):
        return (
            "Username 3-40 karakter, hanya huruf, angka, titik, garis bawah, "
            "atau tanda hubung."
        )
    return None


def validate_password(password):
    """Kembalikan pesan kesalahan, atau None jika password valid."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password minimal {MIN_PASSWORD_LENGTH} karakter."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Password maksimal {MAX_PASSWORD_LENGTH} karakter."
    return None


def create_account(username, password):
    """Buat akun pertama. Gagal bila akun sudah ada."""
    if get_account() is not None:
        raise ValueError("Akun sudah dibuat.")
    _write(username, generate_password_hash(password))


def update_account(username, password=None):
    """Perbarui username dan (opsional) password."""
    password_hash = generate_password_hash(password) if password else None
    _write(username, password_hash)


def _write(username, password_hash):
    username_row = db.session.get(AppSetting, USERNAME_KEY)
    if username_row is None:
        username_row = AppSetting(key=USERNAME_KEY, value=username)
        db.session.add(username_row)
    else:
        username_row.value = username

    if password_hash:
        password_row = db.session.get(AppSetting, PASSWORD_KEY)
        if password_row is None:
            db.session.add(AppSetting(key=PASSWORD_KEY, value=password_hash))
        else:
            password_row.value = password_hash

    db.session.commit()


def check_credentials(username, password):
    """True bila username dan password cocok dengan akun tersimpan."""
    account = get_account()
    if account is None:
        return False
    if not hmac.compare_digest(
        username.encode("utf-8"), account["username"].encode("utf-8")
    ):
        return False
    return check_password_hash(account["password_hash"], password)


def check_password(account, password):
    """True bila password cocok dengan akun yang diberikan."""
    if not account:
        return False
    return check_password_hash(account["password_hash"], password)
