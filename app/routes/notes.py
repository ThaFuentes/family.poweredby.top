import os
import secrets
from datetime import datetime
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import login_required, current_user
from sqlalchemy import or_
from sqlalchemy.orm import selectinload
from werkzeug.utils import secure_filename

from app.builddb.builddb import db
from app.builddb.table_items import Item
from app.builddb.table_note_files import NoteFile
from app.builddb.table_notes import Note, VISIBILITY
from app.builddb.table_users import User
from app.utils.crypto import read_decrypted_file, send_bytes, write_encrypted_file
from app.utils.household import household_id, scoped

notes_bp = Blueprint("notes", __name__, url_prefix="/notes")

ALLOWED_FILES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".pdf"}
MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".pdf": "application/pdf",
}


def _uploads_root():
    root = os.path.join(os.path.dirname(current_app.root_path), "uploads")
    os.makedirs(root, exist_ok=True)
    return root


def _visible(hid, user_id, item_id=None):
    q = Note.query.filter_by(household_id=hid).filter(
        or_(Note.visibility == "household", Note.user_id == user_id)
    )
    if item_id:
        q = q.filter_by(item_id=item_id)
    return q.options(selectinload(Note.files), selectinload(Note.item)).order_by(
        Note.updated_at.desc()
    )


def _can_edit(note) -> bool:
    from app.services.notes import can_edit

    return can_edit(note, current_user)


def _can_see(note) -> bool:
    from app.services.notes import can_see

    return can_see(note, current_user)


def _pin_items(hid):
    return (
        Item.query.filter_by(household_id=hid)
        .order_by(Item.item_type.asc(), Item.name.asc())
        .all()
    )


def _authors(hid):
    return {u.id: u for u in User.query.filter_by(household_id=hid).all()}


def _after_note(note=None, item_id=None):
    if (request.form.get("next") or "") == "sheet":
        target = item_id or (note.item_id if note is not None else None)
        if target:
            return url_for("items.notes_sheet", item_id=target, saved=1)
    if request.form.get("from_item"):
        target = item_id or (note.item_id if note is not None else None)
        if target:
            return url_for("items.detail", item_id=target, tab="notes")
    if note is not None:
        return url_for("notes.index") + f"#note-{note.id}"
    return url_for("notes.index")


def _collect_uploads():
    files = []
    for key in ("file", "photo"):
        files.extend(request.files.getlist(key) or [])
    return files


def save_note_file(note, upload, user_id, caption=None):
    if not note or not upload or not getattr(upload, "filename", None):
        return None
    ext = os.path.splitext(upload.filename)[1].lower()
    if ext not in ALLOWED_FILES:
        return None
    hid = note.household_id
    folder = os.path.join(_uploads_root(), str(hid), "notes", str(note.id))
    os.makedirs(folder, exist_ok=True)
    name = secrets.token_hex(8) + ext + ".enc"
    path = os.path.join(folder, name)
    data = upload.read()
    if not data or len(data) > 20 * 1024 * 1024:
        return None
    write_encrypted_file(path, data)
    orig = secure_filename(upload.filename)[:200] or f"file{ext}"
    row = NoteFile(
        household_id=hid,
        note_id=note.id,
        original_name=orig,
        stored_path=f"{hid}/notes/{note.id}/{name}",
        mime=MIME_BY_EXT.get(ext, "application/octet-stream"),
        caption=(caption or "").strip() or None,
        created_by=user_id,
    )
    db.session.add(row)
    db.session.flush()
    return row


def resolve_note_file(row) -> Path:
    root = Path(_uploads_root()).resolve()
    rel = Path(str(row.stored_path or ""))
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        abort(404)
    if rel.parts[0] != str(row.household_id):
        abort(404)
    path = (root / rel).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        abort(404)
    if not path.is_file():
        abort(404)
    return path


def _unlink_note_file(row):
    try:
        root = Path(_uploads_root()).resolve()
        rel = Path(str(row.stored_path or ""))
        if rel.is_absolute() or ".." in rel.parts or not rel.parts:
            return
        if rel.parts[0] != str(row.household_id):
            return
        path = (root / rel).resolve()
        path.relative_to(root)
        path.unlink(missing_ok=True)
    except Exception:
        pass


def _save_uploads(note, caption=None):
    saved = 0
    for upload in _collect_uploads():
        if save_note_file(note, upload, current_user.id, caption):
            saved += 1
    return saved


@notes_bp.route("/")
@login_required
def index():
    hid = household_id()
    uid = current_user.id
    scope = (request.args.get("scope") or "all").strip().lower()
    q = _visible(hid, uid)
    if scope == "mine":
        q = q.filter_by(user_id=uid)
    elif scope == "household":
        q = q.filter_by(visibility="household")
    elif scope == "pinned":
        q = q.filter(Note.item_id.isnot(None))
    elif scope == "projects":
        q = q.filter(Note.item_id.is_(None))
    rows = q.all()
    return render_template(
        "notes.html",
        rows=rows,
        scope=scope,
        items=_pin_items(hid),
        authors=_authors(hid),
        pin_item_id=request.args.get("item_id") or "",
    )


@notes_bp.route("/add", methods=["POST"])
@login_required
def add():
    from app.services.notes import create_note, resolve_item_id

    item_id = resolve_item_id(request.form.get("item_id"))
    note, err = create_note(
        hid=household_id(),
        user_id=current_user.id,
        title=request.form.get("title"),
        body=request.form.get("body"),
        visibility=request.form.get("visibility") or "personal",
        item_id=item_id,
    )
    if err:
        flash(err, "danger")
        return redirect(request.referrer or url_for("notes.index"))
    n_files = _save_uploads(note, request.form.get("caption"))
    db.session.commit()
    if n_files:
        flash("Note saved with files.", "success")
    else:
        flash("Note saved.", "success")
    return redirect(_after_note(note, item_id=item_id))


@notes_bp.route("/<int:note_id>/edit", methods=["POST"])
@login_required
def edit(note_id):
    note = scoped(Note).filter_by(id=note_id).first_or_404()
    if not _can_edit(note):
        abort(403)
    from app.services.notes import resolve_item_id, update_note

    item_id = resolve_item_id(request.form.get("item_id"))
    err = update_note(
        note,
        title=request.form.get("title"),
        body=request.form.get("body"),
        visibility=request.form.get("visibility") or note.visibility,
        item_id=item_id,
    )
    if err:
        flash(err, "danger")
        return redirect(request.referrer or url_for("notes.index"))
    n_files = _save_uploads(note, request.form.get("caption"))
    db.session.commit()
    flash("Note updated." if not n_files else "Note updated, files saved.", "success")
    return redirect(_after_note(note, item_id=item_id))


@notes_bp.route("/<int:note_id>/file", methods=["POST"])
@login_required
def add_file(note_id):
    note = scoped(Note).filter_by(id=note_id).first_or_404()
    if not _can_see(note):
        abort(403)
    if not _can_edit(note):
        abort(403)
    saved = _save_uploads(note, request.form.get("caption"))
    if not saved:
        flash("Attach a photo or PDF.", "warning")
        return redirect(_after_note(note))
    note.updated_at = datetime.utcnow()
    db.session.commit()
    flash("Saved on this note.", "success")
    return redirect(_after_note(note))


@notes_bp.route("/file/<int:file_id>")
@login_required
def serve_file(file_id):
    row = scoped(NoteFile).options(selectinload(NoteFile.note)).filter_by(id=file_id).first_or_404()
    note = row.note
    if note is None or not _can_see(note):
        abort(404)
    path = resolve_note_file(row)
    ext = os.path.splitext(str(path.name).replace(".enc", ""))[1].lower()
    mime = row.mime or MIME_BY_EXT.get(ext, "application/octet-stream")
    data = read_decrypted_file(str(path))
    name = row.original_name or os.path.basename(str(path)).replace(".enc", "")
    return send_bytes(data, mime, name)


@notes_bp.route("/file/<int:file_id>/delete", methods=["POST"])
@login_required
def delete_file(file_id):
    row = scoped(NoteFile).options(selectinload(NoteFile.note)).filter_by(id=file_id).first_or_404()
    note = row.note
    if note is None or not _can_edit(note):
        abort(403)
    from app.services.notes import remove_note_file

    remove_note_file(row, actor_id=current_user.id, via="ui")
    db.session.commit()
    flash("File removed. A leader can put it back from the recycle bin.", "info")
    return redirect(_after_note(note))


@notes_bp.route("/<int:note_id>/delete", methods=["POST"])
@login_required
def delete(note_id):
    note = (
        scoped(Note)
        .options(selectinload(Note.files))
        .filter_by(id=note_id)
        .first_or_404()
    )
    if not _can_edit(note):
        abort(403)
    from app.services.notes import remove_note

    item_id = note.item_id
    remove_note(note, actor_id=current_user.id, via="ui")
    db.session.commit()
    flash("Note removed. A leader can put it back from the recycle bin.", "info")
    if item_id and (request.form.get("next") or "") == "sheet":
        return redirect(url_for("items.notes_sheet", item_id=item_id, saved=1))
    if item_id and request.form.get("from_item"):
        return redirect(url_for("items.detail", item_id=item_id, tab="notes"))
    return redirect(url_for("notes.index"))
