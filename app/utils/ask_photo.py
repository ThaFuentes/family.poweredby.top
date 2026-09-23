"""Photos dropped into Ask. Kept for this chat until they are filed or cleared.

The bytes sent to the model are a resized JPEG. The copy on disk is encrypted
like every other household upload, and only this household can read it back.
"""
from __future__ import annotations

import base64
import os
import secrets
from io import BytesIO
from pathlib import Path

from flask import current_app, has_request_context, session
from flask_login import current_user

SESSION_PHOTO = "family_ask_photo"
SESSION_MIME = "family_ask_photo_mime"
SESSION_USED = "family_ask_photo_used"
MAX_IN = 8 * 1024 * 1024
MAX_EDGE = 1600


class _MemUpload:
    def __init__(self, data: bytes, filename: str):
        self._data = data
        self.filename = filename

    def read(self):
        data = self._data
        self._data = b""
        return data


def _uploads_root() -> Path:
    root = Path(os.path.dirname(current_app.root_path)) / "uploads"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _hid() -> int:
    return int(getattr(current_user, "household_id", 0) or 0)


def normalize_image(data: bytes) -> tuple[bytes, str] | None:
    if not data or len(data) > MAX_IN:
        return None
    try:
        from PIL import Image
    except Exception:
        return None
    try:
        im = Image.open(BytesIO(data))
        im.load()
    except Exception:
        return None
    if getattr(im, "is_animated", False):
        try:
            im.seek(0)
        except Exception:
            pass
    im = im.convert("RGB")
    w, h = im.size
    edge = max(w, h)
    if edge > MAX_EDGE:
        scale = MAX_EDGE / float(edge)
        im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)
    buf = BytesIO()
    im.save(buf, format="JPEG", quality=82, optimize=True)
    out = buf.getvalue()
    if not out or len(out) > 4 * 1024 * 1024:
        return None
    return out, "image/jpeg"


def decode_image_field(value, mime_hint: str = "") -> tuple[bytes | None, str | None, str | None]:
    """Return jpeg bytes, mime, and an error string when the upload is unusable."""
    if value is None or value == "":
        return None, None, None
    mime = (mime_hint or "").split(";")[0].strip().lower()
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None, None, None
        if s.startswith("data:"):
            header, _, b64 = s.partition(",")
            mime = header[5:].split(";")[0].strip().lower() or mime
            s = b64
        try:
            data = base64.b64decode(s, validate=False)
        except Exception:
            return None, None, "That photo could not be read."
    elif isinstance(value, (bytes, bytearray)):
        data = bytes(value)
    else:
        return None, None, "That photo could not be read."
    if len(data) > MAX_IN:
        return None, None, "Photo is too large. Use one under 8 MB."
    if mime and not mime.startswith("image/"):
        return None, None, "Ask can take a photo, not that file type."
    norm = normalize_image(data)
    if not norm:
        return None, None, "That file is not a photo Ask can read."
    return norm[0], norm[1], None


def image_from_payload(payload: dict | None, file_storage=None):
    if file_storage is not None and getattr(file_storage, "filename", None):
        data = file_storage.read(MAX_IN + 1)
        return decode_image_field(data, getattr(file_storage, "mimetype", "") or "")
    payload = payload if isinstance(payload, dict) else {}
    if payload.get("image"):
        return decode_image_field(payload.get("image"), payload.get("image_mime") or "")
    return None, None, None


def _safe_path(rel: str, hid: int) -> Path | None:
    raw = Path(str(rel or ""))
    if raw.is_absolute() or ".." in raw.parts or len(raw.parts) < 3:
        return None
    if raw.parts[0] != "_ask" or raw.parts[1] != str(hid):
        return None
    root = _uploads_root().resolve()
    path = (root / raw).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


def clear_ask_photo() -> None:
    if not has_request_context():
        return
    rel = session.pop(SESSION_PHOTO, None)
    session.pop(SESSION_MIME, None)
    session.pop(SESSION_USED, None)
    hid = _hid()
    if not rel or not hid:
        return
    path = _safe_path(rel, hid)
    if path is None:
        return
    try:
        if path.is_file():
            path.unlink()
    except Exception:
        pass


def stash_ask_photo(hid: int, data: bytes, mime: str = "image/jpeg") -> bool:
    if not has_request_context() or not hid or not data:
        return False
    clear_ask_photo()
    from app.utils.crypto import write_encrypted_file

    folder = _uploads_root() / "_ask" / str(int(hid))
    folder.mkdir(parents=True, exist_ok=True)
    name = secrets.token_hex(8) + ".jpg"
    written = write_encrypted_file(str(folder / name), data)
    rel = str(Path(written).resolve().relative_to(_uploads_root().resolve()))
    session[SESSION_PHOTO] = rel
    session[SESSION_MIME] = mime or "image/jpeg"
    session[SESSION_USED] = False
    return True


def load_ask_photo() -> tuple[bytes | None, str | None]:
    if not has_request_context():
        return None, None
    rel = session.get(SESSION_PHOTO)
    hid = _hid()
    if not rel or not hid:
        return None, None
    path = _safe_path(rel, hid)
    if path is None or not path.is_file():
        return None, None
    from app.utils.crypto import read_decrypted_file

    try:
        data = read_decrypted_file(str(path))
    except Exception:
        return None, None
    if not data:
        return None, None
    return data, session.get(SESSION_MIME) or "image/jpeg"


def photo_was_attached() -> bool:
    return bool(has_request_context() and session.get(SESSION_USED))


def attach_pending(tool: str, result: dict) -> bool:
    """File the chat photo onto the row a write tool just saved. Once per photo."""
    if not has_request_context() or session.get(SESSION_USED):
        return False
    if not result.get("ok"):
        return False
    data, _mime = load_ask_photo()
    if not data:
        return False
    hid = _hid()
    row_id = result.get("id")
    if not row_id:
        return False
    upload = _MemUpload(data, "ask.jpg")
    saved = None
    if tool == "note_save":
        from app.builddb.table_notes import Note
        from app.routes.notes import save_note_file
        from app.utils.household import scoped

        note = scoped(Note).filter_by(id=int(row_id)).first()
        saved = save_note_file(note, upload, current_user.id, result.get("title"))
    elif tool == "legal_save":
        from app.builddb.table_legal_records import LegalRecord
        from app.routes.legal import save_legal_file
        from app.utils.household import scoped

        record = scoped(LegalRecord).filter_by(id=int(row_id)).first()
        if record is not None:
            saved = save_legal_file(record, upload, current_user.id, result.get("title"))
    elif tool in ("place", "part_save", "tool_save", "vehicle_save", "inventory"):
        from app.builddb.builddb import db
        from app.builddb.table_items import Item
        from app.routes.items import save_item_photo

        item = Item.query.filter_by(id=int(row_id), household_id=hid).first()
        if item is None:
            return False
        saved = save_item_photo(
            item,
            upload,
            caption=result.get("name") or result.get("title"),
            user_id=current_user.id,
            part_id=result.get("part_id"),
            kind="serial" if result.get("serial") else "photo",
        )
        db.session.commit()
        if saved is not None:
            session[SESSION_USED] = True
            return True
        return False
    if saved is None:
        return False
    from app.builddb.builddb import db

    db.session.commit()
    session[SESSION_USED] = True
    return True
