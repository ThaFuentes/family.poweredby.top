"""Recycle bin, archived file versions, and upload cleaning.

Used by the shared services in ``app/services`` so a removal from the UI and
a removal through Maya's API land in the same recycle bin and can be put
back the same way.

* Removing a row snapshots its raw columns (encrypted columns stay
  ciphertext; nothing is decrypted into the snapshot), moves any files to the
  archive folder, then deletes the row. Restore re-inserts the exact row
  (same id) and moves the files back.
* Replacing or removing a file moves the old (still encrypted) bytes to the
  archive folder, which lives OUTSIDE the website folder
  (``FAMILY_ARCHIVE_DIR``, default ``~/familyos_file_archive``).
* Uploads through Maya are sniffed by magic bytes, size-capped, renamed with a
  cleaned name, and photos are re-encoded with EXIF/GPS removed.
"""
from __future__ import annotations

import base64
import io
import os
import secrets
import shutil
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from flask import current_app
from sqlalchemy import text
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from app.builddb.builddb import db

# Only household content can go through the bin. Never people, keys, settings.
TRASHABLE = frozenset({
    "notes", "note_files", "grocery_list", "reminders", "item_logs",
    "legal_records", "legal_files", "legal_followups", "photo_notes",
    "maintenance_records",
})

DEFAULT_MAX_UPLOAD = 10 * 1024 * 1024


# ------------------------------------------------------------- folders


def uploads_root() -> Path:
    root = Path(os.path.dirname(current_app.root_path)) / "uploads"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def archive_root() -> Path:
    raw = (current_app.config.get("FAMILY_ARCHIVE_DIR") or os.getenv("FAMILY_ARCHIVE_DIR") or "").strip()
    root = Path(raw).expanduser() if raw else Path.home() / "familyos_file_archive"
    root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass
    root = root.resolve()
    # Never inside the app folder (which sits in the web root on HostM).
    app_dir = Path(os.path.dirname(current_app.root_path)).resolve()
    try:
        root.relative_to(app_dir)
        raise RuntimeError("FAMILY_ARCHIVE_DIR must be outside the app/docroot folder")
    except ValueError:
        pass
    return root


def _safe_upload_path(hid: int, rel: str) -> Path | None:
    root = uploads_root()
    relp = Path(str(rel or ""))
    if relp.is_absolute() or ".." in relp.parts or not relp.parts:
        return None
    if relp.parts[0] != str(int(hid)):
        return None
    path = (root / relp).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


def archive_file(hid: int, rel: str) -> str | None:
    """Move uploads/<rel> into the archive. Returns the archived absolute path."""
    src = _safe_upload_path(hid, rel)
    if src is None or not src.is_file():
        return None
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    dest_dir = archive_root() / str(int(hid)) / f"{stamp}_{secrets.token_hex(4)}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    shutil.move(str(src), str(dest))
    return str(dest)


def _archived_ok(path: str) -> Path | None:
    p = Path(str(path or "")).resolve()
    try:
        p.relative_to(archive_root())
    except ValueError:
        return None
    return p if p.is_file() else None


def unarchive_file(hid: int, archived: str, rel: str) -> bool:
    src = _archived_ok(archived)
    dest = _safe_upload_path(hid, rel)
    if src is None or dest is None or dest.exists():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return True


# ------------------------------------------------------------ snapshots


def _jsonable(value):
    if value is None or isinstance(value, (int, float, str, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__b64__": base64.b64encode(bytes(value)).decode("ascii")}
    return str(value)


def _unjson(value):
    if isinstance(value, dict) and "__b64__" in value:
        return base64.b64decode(value["__b64__"])
    return value


def snapshot(model, obj) -> dict:
    """Raw column values straight from the table (ciphertext stays ciphertext)."""
    table = model.__tablename__
    pk = list(model.__table__.primary_key.columns)[0].name
    db.session.flush()
    row = db.session.execute(
        text(f"SELECT * FROM `{table}` WHERE `{pk}` = :v"), {"v": getattr(obj, pk)}
    ).mappings().first()
    return {"table": table, "pk": pk, "row": {k: _jsonable(v) for k, v in dict(row or {}).items()}}


def trash(*, hid: int, label: str, rows: list, files: list[str] | None = None,
          actor_id=None, via: str = "ui"):
    """rows: [(Model, obj), ...] parent first. Children are deleted first."""
    from app.builddb.table_maya_bot import HouseholdTrash

    if not rows:
        return None
    for model, _obj in rows:
        if model.__tablename__ not in TRASHABLE:
            raise PermissionError(f"{model.__tablename__} cannot go through the recycle bin")
    snaps = [snapshot(model, obj) for model, obj in rows]
    moved = []
    for rel in files or []:
        archived = archive_file(hid, rel)
        if archived:
            moved.append({"rel": rel, "archived": archived})
    for _model, obj in reversed(rows):
        db.session.delete(obj)
    first_model, first_obj = rows[0]
    pk = snaps[0]["pk"]
    entry = HouseholdTrash(
        household_id=int(hid),
        target_table=first_model.__tablename__,
        target_id=int(getattr(first_obj, pk)),
        label=(label or first_model.__tablename__)[:240],
        rows_json=snaps,
        files_json=moved or None,
        deleted_by=actor_id,
        via=(via or "ui")[:16],
    )
    db.session.add(entry)
    db.session.flush()
    return entry


def restore(entry, *, actor_id=None) -> tuple[bool, str]:
    if entry is None:
        return False, "Nothing to restore."
    if entry.restored_at is not None:
        return False, "Already put back."
    if entry.purged_at is not None:
        return False, "That one was permanently deleted."
    snaps = entry.rows_json if isinstance(entry.rows_json, list) else []
    for snap in snaps:
        table, pk, row = snap.get("table"), snap.get("pk"), snap.get("row") or {}
        if table not in TRASHABLE or not row:
            return False, "That entry cannot be restored."
        exists = db.session.execute(
            text(f"SELECT 1 FROM `{table}` WHERE `{pk}` = :v"), {"v": row.get(pk)}
        ).first()
        if exists:
            return False, "Something with that id is already back."
    try:
        for snap in snaps:
            table, row = snap["table"], snap["row"]
            cols = list(row.keys())
            sql = (
                f"INSERT INTO `{table}` (" + ", ".join(f"`{c}`" for c in cols) + ") VALUES ("
                + ", ".join(f":c{i}" for i in range(len(cols))) + ")"
            )
            db.session.execute(text(sql), {f"c{i}": _unjson(row[c]) for i, c in enumerate(cols)})
        for f in entry.files_json or []:
            unarchive_file(entry.household_id, f.get("archived"), f.get("rel"))
        entry.restored_at = datetime.utcnow()
        entry.restored_by = actor_id
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return False, f"Could not put that back: {exc.__class__.__name__}"
    return True, f"Put back: {entry.label}."


def purge(entry, *, actor_id=None) -> tuple[bool, str]:
    """Hard delete (high risk). Drops archived bytes; the bin row stays as audit."""
    if entry is None or entry.restored_at is not None or entry.purged_at is not None:
        return False, "Nothing to purge."
    for f in entry.files_json or []:
        p = _archived_ok(f.get("archived"))
        if p is not None:
            try:
                p.unlink()
            except OSError:
                pass
    entry.rows_json = None
    entry.files_json = None
    entry.purged_at = datetime.utcnow()
    entry.purged_by = actor_id
    db.session.commit()
    return True, "Permanently deleted. The audit line stays."


# --------------------------------------------------------- file versions

KIND_MODEL = {
    "note_file": ("app.builddb.table_note_files", "NoteFile", "stored_path"),
    "photo": ("app.builddb.table_photo_notes", "PhotoNote", "image_path"),
    "legal_file": ("app.builddb.table_legal_files", "LegalFile", "stored_path"),
}


def kind_model(kind: str):
    import importlib

    if kind not in KIND_MODEL:
        return None, None
    mod, cls, attr = KIND_MODEL[kind]
    return getattr(importlib.import_module(mod), cls), attr


def keep_version(*, hid: int, kind: str, row, reason: str, actor_id=None):
    """Move the row's current bytes into the archive and record a version."""
    from app.builddb.table_maya_bot import HouseholdFileVersion

    _model, attr = kind_model(kind)
    rel = getattr(row, attr, None)
    archived = archive_file(hid, rel) if rel else None
    if not archived:
        return None
    ver = HouseholdFileVersion(
        household_id=int(hid),
        kind=kind,
        row_id=int(row.id),
        stored_rel=str(rel),
        archived_path=archived,
        original_name=getattr(row, "original_name", None),
        mime=getattr(row, "mime", None),
        reason=reason[:16],
        created_by=actor_id,
    )
    db.session.add(ver)
    db.session.flush()
    return ver


def restore_version(ver, row, *, actor_id=None) -> tuple[bool, str, int | None]:
    """Put an archived version back as the row's current file.

    The file the row has now is archived first. The third value is that new
    archive id, so Happened can put this restore back too.
    """
    if ver is None or row is None or ver.restored_at is not None:
        return False, "That version is not available.", None
    _model, attr = kind_model(ver.kind)
    archived_id = None
    if getattr(row, attr, None):
        archived = keep_version(hid=ver.household_id, kind=ver.kind, row=row, reason="replace", actor_id=actor_id)
        archived_id = int(archived.id) if archived is not None else None
    src_rel = Path(ver.stored_rel)
    new_rel = str(src_rel.parent / (secrets.token_hex(8) + "".join(src_rel.suffixes[-2:])))
    if not unarchive_file(ver.household_id, ver.archived_path, new_rel):
        return False, "The archived bytes are missing.", None
    setattr(row, attr, new_rel)
    if ver.original_name and hasattr(row, "original_name"):
        row.original_name = ver.original_name
    if ver.mime and hasattr(row, "mime"):
        row.mime = ver.mime
    ver.restored_at = datetime.utcnow()
    db.session.commit()
    return True, "Old version restored.", archived_id


def write_replacement(*, hid: int, kind: str, row, upload: FileStorage, actor_id=None) -> tuple[bool, str, int | None]:
    """Archive the current bytes, write the cleaned upload encrypted in place.

    The third value is the archived version id. Happened uses it to put the
    old bytes back. None means the archive did not keep a copy.
    """
    from app.utils.crypto import write_encrypted_file

    _model, attr = kind_model(kind)
    rel_old = getattr(row, attr, None)
    if not rel_old:
        return False, "That file has no stored bytes.", None
    ver = keep_version(hid=hid, kind=kind, row=row, reason="replace", actor_id=actor_id)
    ext = os.path.splitext(upload.filename or "")[1].lower() or ".bin"
    folder = Path(rel_old).parent
    new_rel = str(folder / (secrets.token_hex(8) + ext + ".enc"))
    dest = _safe_upload_path(hid, new_rel)
    if dest is None:
        return False, "Bad storage path.", None
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_encrypted_file(str(dest), upload.read())
    setattr(row, attr, new_rel)
    if hasattr(row, "original_name"):
        row.original_name = upload.filename[:200]
    if hasattr(row, "mime") and upload.mimetype:
        row.mime = upload.mimetype[:80]
    return True, "Replaced. The old version is archived.", (int(ver.id) if ver is not None else None)


# ------------------------------------------------------------- uploads

_SNIFF = (
    (b"\xff\xd8\xff", ".jpg", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", ".png", "image/png"),
    (b"GIF87a", ".gif", "image/gif"),
    (b"GIF89a", ".gif", "image/gif"),
    (b"%PDF-", ".pdf", "application/pdf"),
)
IMAGE_EXTS = frozenset({".jpg", ".png", ".webp", ".gif"})
PHOTO_EXTS = IMAGE_EXTS
DOC_EXTS = IMAGE_EXTS | {".pdf"}


def sniff(data: bytes) -> tuple[str, str] | None:
    for magic, ext, mime in _SNIFF:
        if data.startswith(magic):
            return ext, mime
    if len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp", "image/webp"
    return None


def strip_exif(data: bytes, ext: str) -> bytes:
    """Re-encode the picture with no EXIF/GPS/XMP. Orientation is applied first."""
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(data)) as probe:
        probe.verify()
    with Image.open(io.BytesIO(data)) as img:
        img.load()
        if ext == ".gif":
            fmt, kw = "GIF", {"save_all": getattr(img, "is_animated", False)}
            out_img = img
        else:
            out_img = ImageOps.exif_transpose(img)
            fmt = {".jpg": "JPEG", ".png": "PNG", ".webp": "WEBP"}[ext]
            kw = {"quality": 92} if fmt in ("JPEG", "WEBP") else {}
            if fmt == "JPEG" and out_img.mode not in ("RGB", "L"):
                out_img = out_img.convert("RGB")
        out_img.info = {}
        buf = io.BytesIO()
        out_img.save(buf, format=fmt, **kw)
        return buf.getvalue()


def clean_name(raw: str, ext: str) -> str:
    stem = os.path.splitext(os.path.basename(str(raw or "")))[0]
    stem = secure_filename(stem)[:80] or "file"
    return stem + ext


def clean_upload(upload, *, allowed: frozenset, max_bytes: int | None = None):
    """(FileStorage, None) or (None, error). The returned file is cleaned."""
    if upload is None or not getattr(upload, "filename", None):
        return None, "Send the file as multipart field 'file'."
    cap = int(max_bytes or current_app.config.get("MAYA_UPLOAD_MAX_BYTES") or DEFAULT_MAX_UPLOAD)
    data = upload.read(cap + 1)
    if not data:
        return None, "That file is empty."
    if len(data) > cap:
        return None, f"That file is over {cap // (1024 * 1024)} MB."
    found = sniff(data)
    if found is None:
        return None, "Only JPG, PNG, WEBP, GIF or PDF files."
    ext, mime = found
    if ext not in allowed:
        return None, "That file type is not allowed here."
    claimed = os.path.splitext(upload.filename)[1].lower().replace(".jpeg", ".jpg")
    if claimed and claimed != ext:
        # Trust the bytes, not the name.
        pass
    if ext in IMAGE_EXTS:
        try:
            data = strip_exif(data, ext)
        except Exception:
            return None, "That picture could not be read."
    return FileStorage(io.BytesIO(data), filename=clean_name(upload.filename, ext), content_type=mime), None
