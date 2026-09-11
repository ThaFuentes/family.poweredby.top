import os
import secrets
from datetime import datetime
from decimal import Decimal, InvalidOperation
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
from werkzeug.utils import secure_filename

from app.builddb.builddb import db
from app.builddb.table_legal_files import LegalFile
from app.builddb.table_legal_records import (
    KINDS,
    KIND_LABELS,
    STATUSES,
    STATUS_LABELS,
    LegalRecord,
)
from app.builddb.table_users import User
from app.utils.crypto import sendable_image, write_encrypted_file
from app.utils.household import household_id, scoped
from app.utils.permissions import can, require_perm

legal_bp = Blueprint("legal", __name__, url_prefix="/legal")

ALLOWED_FILES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".pdf"}
MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".pdf": "application/pdf",
}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _parse_date(raw):
    s = (raw or "").strip()[:10]
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _parse_amount(raw):
    s = (raw or "").strip().replace("$", "").replace(",", "")
    if not s:
        return None
    try:
        d = Decimal(s)
    except (InvalidOperation, ValueError):
        return None
    if d < 0 or d > Decimal("99999999.99"):
        return None
    return d.quantize(Decimal("0.01"))


def _kind(raw, fallback="citation"):
    k = (raw or "").strip().lower()
    return k if k in KINDS else fallback


def _status(raw, fallback="open"):
    s = (raw or "").strip().lower()
    return s if s in STATUSES else fallback


def _uploads_root():
    root = os.path.join(os.path.dirname(current_app.root_path), "uploads")
    os.makedirs(root, exist_ok=True)
    return root


def _can_edit(row: LegalRecord) -> bool:
    if not can("legal"):
        return False
    if current_user.id == row.created_by:
        return True
    return bool(getattr(current_user, "is_admin", False) or getattr(current_user, "is_leader", False))


def _authors(hid):
    return {u.id: u for u in User.query.filter_by(household_id=hid).all()}


def _agency_counts(rows):
    counts = {}
    for r in rows:
        key = (r.agency or "").strip() or "Unknown"
        counts[key] = counts.get(key, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))


def save_legal_file(record, upload, user_id, caption=None):
    if not upload or not getattr(upload, "filename", None):
        return None
    ext = os.path.splitext(upload.filename)[1].lower()
    if ext not in ALLOWED_FILES:
        return None
    hid = record.household_id
    folder = os.path.join(_uploads_root(), str(hid), "legal", str(record.id))
    os.makedirs(folder, exist_ok=True)
    name = secrets.token_hex(8) + ext + ".enc"
    path = os.path.join(folder, name)
    data = upload.read()
    if not data or len(data) > 20 * 1024 * 1024:
        return None
    write_encrypted_file(path, data)
    orig = secure_filename(upload.filename)[:200] or f"file{ext}"
    row = LegalFile(
        household_id=hid,
        record_id=record.id,
        original_name=orig,
        stored_path=f"{hid}/legal/{record.id}/{name}",
        mime=MIME_BY_EXT.get(ext, "application/octet-stream"),
        caption=(caption or "").strip() or None,
        created_by=user_id,
    )
    db.session.add(row)
    db.session.flush()
    return row


def resolve_legal_file(row) -> Path:
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


def _form_record(row=None):
    title = (request.form.get("title") or "").strip()
    if not title:
        return None, "Say what it is — parking ticket, code notice, whatever they handed you."
    kind = _kind(request.form.get("kind"), row.kind if row else "citation")
    status = _status(request.form.get("status"), row.status if row else "open")
    extra = {}
    if row is not None and isinstance(getattr(row, "extra_data", None), dict):
        extra = dict(row.extra_data)
    detail = (request.form.get("kind_detail") or "").strip()[:200]
    if detail:
        extra["kind_detail"] = detail
    else:
        extra.pop("kind_detail", None)
    return {
        "title": title[:500],
        "kind": kind,
        "status": status,
        "agency": (request.form.get("agency") or "").strip()[:400] or None,
        "case_number": (request.form.get("case_number") or "").strip()[:120] or None,
        "location": (request.form.get("location") or "").strip()[:400] or None,
        "issued_on": _parse_date(request.form.get("issued_on")),
        "due_on": _parse_date(request.form.get("due_on")),
        "amount": _parse_amount(request.form.get("amount")),
        "body": (request.form.get("body") or "").strip() or None,
        "outcome": (request.form.get("outcome") or "").strip() or None,
        "extra_data": extra or None,
    }, None


@legal_bp.route("/")
@login_required
@require_perm("legal")
def index():
    hid = household_id()
    kind = _kind(request.args.get("kind"), "")
    status = _status(request.args.get("status"), "")
    agency_q = (request.args.get("agency") or "").strip()
    q = scoped(LegalRecord)
    if kind:
        q = q.filter_by(kind=kind)
    if status:
        q = q.filter_by(status=status)
    rows = q.order_by(LegalRecord.issued_on.desc(), LegalRecord.id.desc()).limit(300).all()
    if agency_q:
        needle = agency_q.lower()
        rows = [r for r in rows if needle in (r.agency or "").lower()]
    all_rows = scoped(LegalRecord).all()
    return render_template(
        "legal.html",
        rows=rows,
        kinds=KINDS,
        kind_labels=KIND_LABELS,
        statuses=STATUSES,
        status_labels=STATUS_LABELS,
        kind=kind,
        status=status,
        agency_q=agency_q,
        agencies=_agency_counts(all_rows),
        authors=_authors(hid),
        open_count=sum(1 for r in all_rows if r.status == "open"),
        total_count=len(all_rows),
    )


@legal_bp.route("/add", methods=["POST"])
@login_required
@require_perm("legal")
def add():
    fields, err = _form_record()
    if err:
        flash(err, "danger")
        return redirect(url_for("legal.index"))
    row = LegalRecord(household_id=household_id(), created_by=current_user.id, **fields)
    db.session.add(row)
    db.session.flush()
    files = request.files.getlist("file") or []
    saved = 0
    for f in files:
        if save_legal_file(row, f, current_user.id, request.form.get("caption")):
            saved += 1
    db.session.commit()
    flash("Saved to the record." + (f" {saved} file(s) attached." if saved else ""), "success")
    return redirect(url_for("legal.detail", record_id=row.id))


@legal_bp.route("/<int:record_id>")
@login_required
@require_perm("legal")
def detail(record_id):
    row = scoped(LegalRecord).filter_by(id=record_id).first_or_404()
    author = User.query.filter_by(id=row.created_by).first() if row.created_by else None
    return render_template(
        "legal_detail.html",
        row=row,
        author=author,
        kinds=KINDS,
        kind_labels=KIND_LABELS,
        statuses=STATUSES,
        status_labels=STATUS_LABELS,
        can_edit=_can_edit(row),
        image_exts=IMAGE_EXTS,
    )


@legal_bp.route("/<int:record_id>/edit", methods=["POST"])
@login_required
@require_perm("legal")
def edit(record_id):
    row = scoped(LegalRecord).filter_by(id=record_id).first_or_404()
    if not _can_edit(row):
        abort(403)
    fields, err = _form_record(row)
    if err:
        flash(err, "danger")
        return redirect(url_for("legal.detail", record_id=row.id))
    for key, val in fields.items():
        setattr(row, key, val)
    row.updated_at = datetime.utcnow()
    db.session.commit()
    flash("Record updated.", "success")
    return redirect(url_for("legal.detail", record_id=row.id))


@legal_bp.route("/<int:record_id>/delete", methods=["POST"])
@login_required
@require_perm("legal")
def delete(record_id):
    row = scoped(LegalRecord).filter_by(id=record_id).first_or_404()
    if not _can_edit(row):
        abort(403)
    hid = row.household_id
    folder = Path(_uploads_root()) / str(hid) / "legal" / str(row.id)
    root = Path(_uploads_root()).resolve()
    if folder.exists():
        try:
            folder.resolve().relative_to(root)
            import shutil

            shutil.rmtree(folder, ignore_errors=True)
        except ValueError:
            pass
    LegalFile.query.filter_by(household_id=hid, record_id=row.id).delete(synchronize_session=False)
    db.session.delete(row)
    db.session.commit()
    flash("Record removed.", "info")
    return redirect(url_for("legal.index"))


@legal_bp.route("/<int:record_id>/file", methods=["POST"])
@login_required
@require_perm("legal")
def add_file(record_id):
    row = scoped(LegalRecord).filter_by(id=record_id).first_or_404()
    if not _can_edit(row):
        abort(403)
    files = request.files.getlist("file") or []
    saved = 0
    for f in files:
        if save_legal_file(row, f, current_user.id, request.form.get("caption")):
            saved += 1
    if not saved:
        flash("Attach a photo or PDF of the paper.", "warning")
        return redirect(url_for("legal.detail", record_id=row.id))
    db.session.commit()
    flash("File saved on this record.", "success")
    return redirect(url_for("legal.detail", record_id=row.id))


@legal_bp.route("/file/<int:file_id>")
@login_required
@require_perm("legal")
def serve_file(file_id):
    row = scoped(LegalFile).filter_by(id=file_id).first_or_404()
    path = resolve_legal_file(row)
    ext = os.path.splitext(str(path.name).replace(".enc", ""))[1].lower()
    mime = row.mime or MIME_BY_EXT.get(ext, "application/octet-stream")
    return sendable_image(path, mime)


@legal_bp.route("/file/<int:file_id>/delete", methods=["POST"])
@login_required
@require_perm("legal")
def delete_file(file_id):
    row = scoped(LegalFile).filter_by(id=file_id).first_or_404()
    record_id = row.record_id
    rec = scoped(LegalRecord).filter_by(id=record_id).first_or_404()
    if not _can_edit(rec):
        abort(403)
    try:
        path = resolve_legal_file(row)
        path.unlink(missing_ok=True)
    except Exception:
        pass
    db.session.delete(row)
    db.session.commit()
    flash("File removed.", "info")
    return redirect(url_for("legal.detail", record_id=record_id))
