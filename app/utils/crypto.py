"""Household data at rest. Fernet for notes, captions, and photo bytes.

Plaintext already in the DB is left readable. New writes are encrypted.
A missing or rotated key never 500s a page — decrypt falls back to the raw value.
"""
from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy.types import Text, TypeDecorator

_FILE_MAGIC = b"FAMENC1\n"
_fernet: Fernet | None = None


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _persist_key(key: str) -> None:
    env_path = _project_root() / ".env"
    try:
        text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
        if "FAMILY_DATA_KEY=" in text:
            return
        with env_path.open("a", encoding="utf-8") as fh:
            if text and not text.endswith("\n"):
                fh.write("\n")
            fh.write("# Fernet key for notes / captions / photos. Do not rotate casually.\n")
            fh.write(f"FAMILY_DATA_KEY={key}\n")
    except Exception:
        pass


def _fernet_from_secret(secret: str) -> Fernet:
    secret = (secret or "").strip()
    if len(secret) == 44 and secret.endswith("="):
        try:
            return Fernet(secret.encode("utf-8"))
        except Exception:
            pass
    material = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"family.poweredby.top.hkdf.v1",
        info=b"household-data",
    ).derive(secret.encode("utf-8"))
    import base64

    return Fernet(base64.urlsafe_b64encode(material))


def _shared_key_path() -> Path:
    return _project_root() / "uploads" / ".family_data_key"


def _read_shared_key() -> str:
    try:
        p = _shared_key_path()
        if p.is_file():
            return p.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""


def _write_shared_key(key: str) -> None:
    try:
        p = _shared_key_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.is_file() and p.read_text(encoding="utf-8").strip():
            return
        p.write_text(key.strip() + "\n", encoding="utf-8")
        try:
            os.chmod(p, 0o600)
        except Exception:
            pass
    except Exception:
        pass


def get_platform_fernet() -> Fernet | None:
    global _fernet
    if _fernet is not None:
        return _fernet
    key = (os.getenv("FAMILY_DATA_KEY") or "").strip() or _read_shared_key()
    if not key:
        generated = Fernet.generate_key().decode("ascii")
        _persist_key(generated)
        _write_shared_key(generated)
        key = _read_shared_key() or generated
        os.environ["FAMILY_DATA_KEY"] = key
    else:
        os.environ["FAMILY_DATA_KEY"] = key
        _write_shared_key(key)
    try:
        _fernet = _fernet_from_secret(key)
        return _fernet
    except Exception:
        secret = (os.getenv("SECRET_KEY") or "").strip()
        if not secret:
            return None
        try:
            _fernet = _fernet_from_secret(secret)
            return _fernet
        except Exception:
            return None


def get_fernet() -> Fernet | None:
    """Household lock while unlocked, else the site-wide data key."""
    try:
        from app.utils.household_vault import session_fernet

        house = session_fernet()
        if house is not None:
            return house
    except Exception:
        pass
    return get_platform_fernet()


def _fernets_to_try() -> list[Fernet]:
    out: list[Fernet] = []
    try:
        from app.utils.household_vault import session_fernet

        house = session_fernet()
        if house is not None:
            out.append(house)
    except Exception:
        pass
    platform = get_platform_fernet()
    if platform is not None and platform not in out:
        out.append(platform)
    return out


def looks_encrypted(value) -> bool:
    if value is None:
        return False
    if isinstance(value, (bytes, bytearray, memoryview)):
        head = bytes(value[:8])
        try:
            head = head.decode("ascii", errors="ignore")
        except Exception:
            return False
    else:
        head = str(value)[:8]
    return head.startswith("gAAAAA")


def encrypt_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value)
    if text == "" or looks_encrypted(text):
        return text
    f = get_fernet()
    if f is None:
        return text
    try:
        return f.encrypt(text.encode("utf-8")).decode("ascii")
    except Exception:
        return text


def decrypt_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value)
    if not looks_encrypted(text):
        return text
    keys = _fernets_to_try()
    if not keys:
        return text
    raw = text.encode("ascii")
    for f in keys:
        try:
            return f.decrypt(raw).decode("utf-8")
        except (InvalidToken, Exception):
            continue
    return text


def encrypt_bytes(data: bytes) -> bytes:
    if not data:
        return data
    if data.startswith(_FILE_MAGIC):
        return data
    # Files on disk use the site key so every Passenger worker can read them.
    f = get_platform_fernet()
    if f is None:
        return data
    try:
        return _FILE_MAGIC + f.encrypt(data)
    except Exception:
        return data


def decrypt_bytes(data: bytes) -> bytes:
    if not data:
        return data
    keys = _fernets_to_try()
    platform = get_platform_fernet()
    if platform is not None and platform not in keys:
        keys.append(platform)
    if not keys:
        return data
    blob = data
    wrapped = blob.startswith(_FILE_MAGIC)
    if wrapped:
        blob = blob[len(_FILE_MAGIC) :]
    elif not looks_encrypted(blob):
        return data
    for f in keys:
        try:
            return f.decrypt(blob)
        except (InvalidToken, Exception):
            continue
    if wrapped or looks_encrypted(data):
        return b""
    return data


class EncryptedText(TypeDecorator):
    """SQLAlchemy TEXT that encrypts on write and decrypts on read."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt_text(value)

    def process_result_value(self, value, dialect):
        return decrypt_text(value)


def encrypted_upload_path(path: str) -> str:
    return path if path.endswith(".enc") else path + ".enc"


def write_encrypted_file(path: str, data: bytes) -> str:
    out = encrypted_upload_path(path)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_bytes(encrypt_bytes(data))
    return out


def read_decrypted_file(path: str) -> bytes:
    raw = Path(path).read_bytes()
    return decrypt_bytes(raw)


def send_bytes(data: bytes, mimetype: str, filename: str = "file"):
    """Passenger stdout is not a real file — never send_file(BytesIO) (fileno)."""
    from flask import Response, abort

    if not data:
        abort(404)
    if data.startswith(_FILE_MAGIC) or looks_encrypted(data):
        abort(404)
    name = os.path.basename(filename or "file").replace('"', "")
    resp = Response(data, mimetype=mimetype or "application/octet-stream")
    resp.headers["Content-Length"] = str(len(data))
    resp.headers["Content-Disposition"] = f'inline; filename="{name}"'
    resp.headers["Cache-Control"] = "private, max-age=86400"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


def sendable_image(path: str, mimetype: str):
    data = read_decrypted_file(path)
    return send_bytes(data, mimetype, os.path.basename(path).replace(".enc", ""))
