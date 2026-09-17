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
from sqlalchemy.orm import joinedload, selectinload
from werkzeug.utils import secure_filename

from app.builddb.builddb import db
from app.builddb.table_legal_cases import (
    CASE_STATUSES,
    CASE_STATUS_LABELS,
    LegalCase,
    case_label,
    next_case_number,
)
from app.builddb.table_legal_files import LegalFile
from app.builddb.table_legal_followups import FOLLOWUP_KINDS, FOLLOWUP_LABELS, LegalFollowup
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

ALLOWED_FILES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".pdf", ".eml", ".msg"}
MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".pdf": "application/pdf",
    ".eml": "message/rfc822",
    ".msg": "application/vnd.ms-outlook",
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


def _can_edit(row) -> bool:
    if not can("legal"):
        return False
    if getattr(row, "created_by", None) == current_user.id:
        return True
    return bool(getattr(current_user, "is_admin", False) or getattr(current_user, "is_leader", False))


def _paper_files(row: LegalRecord):
    return [f for f in (row.files or []) if not getattr(f, "followup_id", None)]


def _authors(hid):
    return {u.id: u for u in User.query.filter_by(household_id=hid).all()}


def _agency_counts(rows):
    counts = {}
    for r in rows:
        key = (r.agency or "").strip() or "Unknown"
        counts[key] = counts.get(key, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))


def save_legal_file(record, upload, user_id, caption=None, *, case=None, followup=None):
    if not upload or not getattr(upload, "filename", None):
        return None
    ext = os.path.splitext(upload.filename)[1].lower()
    if ext not in ALLOWED_FILES:
        return None
    if record is None and followup is not None:
        record = followup.case.records[0] if followup.case and followup.case.records else None
    if record is None and case is not None and case.records:
        record = case.records[0]
    hid = (record.household_id if record is not None else None) or (
        case.household_id if case is not None else None
    ) or (followup.household_id if followup is not None else None)
    if not hid:
        return None
    case_id = (case.id if case is not None else None) or (
        followup.case_id if followup is not None else None
    )
    sub = f"followups/{followup.id}" if followup is not None else (
        f"cases/{case_id}" if case_id and record is None else str((record.id if record else "x"))
    )
    folder = os.path.join(_uploads_root(), str(hid), "legal", sub)
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
        record_id=record.id if record is not None else None,
        case_id=case_id,
        followup_id=followup.id if followup is not None else None,
        original_name=orig,
        stored_path=f"{hid}/legal/{sub}/{name}",
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
    view = (request.args.get("view") or "records").strip().lower()
    if view not in ("records", "cases"):
        view = "records"
    kind = _kind(request.args.get("kind"), "")
    status = _status(request.args.get("status"), "")
    agency_q = (request.args.get("agency") or "").strip()
    q = scoped(LegalRecord).options(joinedload(LegalRecord.case))
    if kind:
        q = q.filter_by(kind=kind)
    if status:
        q = q.filter_by(status=status)
    rows = q.order_by(LegalRecord.issued_on.desc(), LegalRecord.id.desc()).limit(300).all()
    if agency_q:
        needle = agency_q.lower()
        rows = [r for r in rows if needle in (r.agency or "").lower()]
    all_rows = scoped(LegalRecord).all()
    cases = (
        scoped(LegalCase)
        .options(selectinload(LegalCase.records), selectinload(LegalCase.followups))
        .order_by(LegalCase.number.desc())
        .limit(200)
        .all()
    )
    return render_template(
        "legal.html",
        rows=rows,
        cases=cases,
        view=view,
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
        case_count=len(cases),
        case_label=case_label,
        case_status_labels=CASE_STATUS_LABELS,
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


def _open_case_from_record(row: LegalRecord, title=None):
    hid = household_id()
    if row.case_id:
        return row.case
    case = LegalCase(
        household_id=hid,
        number=next_case_number(hid),
        title=(title or row.title or "Case")[:500],
        status="open",
        summary=row.body,
        created_by=current_user.id,
    )
    db.session.add(case)
    db.session.flush()
    row.case_id = case.id
    return case


@legal_bp.route("/cases", methods=["GET", "POST"])
@login_required
@require_perm("legal")
def add_case():
    if request.method == "GET":
        return redirect(url_for("legal.index", view="cases"))
    hid = household_id()
    title = (request.form.get("title") or "").strip()
    if not title:
        flash("Name the case.", "danger")
        return redirect(url_for("legal.index", view="cases"))
    case = LegalCase(
        household_id=hid,
        number=next_case_number(hid),
        title=title[:500],
        status="open",
        summary=(request.form.get("summary") or "").strip() or None,
        created_by=current_user.id,
    )
    db.session.add(case)
    db.session.flush()
    rec_id = request.form.get("record_id")
    if rec_id:
        rec = scoped(LegalRecord).filter_by(id=int(rec_id)).first()
        if rec and not rec.case_id:
            rec.case_id = case.id
    db.session.commit()
    flash(f"{case_label(case)} opened.", "success")
    return redirect(url_for("legal.case_detail", case_id=case.id))


@legal_bp.route("/cases/<int:case_id>")
@login_required
@require_perm("legal")
def case_detail(case_id):
    hid = household_id()
    case = (
        scoped(LegalCase)
        .options(
            selectinload(LegalCase.records).selectinload(LegalRecord.files),
            selectinload(LegalCase.followups).selectinload(LegalFollowup.files),
        )
        .filter_by(id=case_id)
        .first_or_404()
    )
    author = User.query.filter_by(id=case.created_by).first() if case.created_by else None
    loose = (
        scoped(LegalRecord)
        .filter(LegalRecord.case_id.is_(None))
        .order_by(LegalRecord.issued_on.desc(), LegalRecord.id.desc())
        .limit(80)
        .all()
    )
    return render_template(
        "legal_case.html",
        case=case,
        author=author,
        case_label=case_label(case),
        followup_kinds=FOLLOWUP_KINDS,
        followup_labels=FOLLOWUP_LABELS,
        case_statuses=CASE_STATUSES,
        case_status_labels=CASE_STATUS_LABELS,
        kind_labels=KIND_LABELS,
        status_labels=STATUS_LABELS,
        can_edit=_can_edit(case),
        authors=_authors(hid),
        loose_records=loose,
        paper_files=_paper_files,
        image_exts=IMAGE_EXTS,
    )


@legal_bp.route("/cases/<int:case_id>/edit", methods=["POST"])
@login_required
@require_perm("legal")
def edit_case(case_id):
    case = scoped(LegalCase).filter_by(id=case_id).first_or_404()
    if not _can_edit(case):
        abort(403)
    title = (request.form.get("title") or "").strip()
    if title:
        case.title = title[:500]
    st = (request.form.get("status") or "").strip().lower()
    if st in CASE_STATUSES:
        case.status = st
    case.summary = (request.form.get("summary") or "").strip() or None
    case.updated_at = datetime.utcnow()
    db.session.commit()
    flash(f"{case_label(case)} updated.", "success")
    return redirect(url_for("legal.case_detail", case_id=case.id))


@legal_bp.route("/<int:record_id>/open-case", methods=["POST"])
@login_required
@require_perm("legal")
def open_case(record_id):
    row = scoped(LegalRecord).filter_by(id=record_id).first_or_404()
    if not _can_edit(row):
        abort(403)
    title = (request.form.get("title") or "").strip() or None
    case = _open_case_from_record(row, title=title)
    db.session.commit()
    flash(f"{case_label(case)} opened. This {KIND_LABELS.get(row.kind, 'record')} stays searchable on its own.", "success")
    return redirect(url_for("legal.case_detail", case_id=case.id))


@legal_bp.route("/<int:record_id>/attach-case", methods=["POST"])
@login_required
@require_perm("legal")
def attach_case(record_id):
    row = scoped(LegalRecord).filter_by(id=record_id).first_or_404()
    if not _can_edit(row):
        abort(403)
    try:
        cid = int(request.form.get("case_id") or 0)
    except (TypeError, ValueError):
        cid = 0
    case = scoped(LegalCase).filter_by(id=cid).first()
    if case is None:
        flash("Pick a case.", "warning")
        return redirect(url_for("legal.detail", record_id=row.id))
    row.case_id = case.id
    db.session.commit()
    flash(f"Tied to {case_label(case)}.", "success")
    return redirect(url_for("legal.case_detail", case_id=case.id))


@legal_bp.route("/<int:record_id>/detach-case", methods=["POST"])
@login_required
@require_perm("legal")
def detach_case(record_id):
    row = scoped(LegalRecord).filter_by(id=record_id).first_or_404()
    if not _can_edit(row):
        abort(403)
    cid = row.case_id
    row.case_id = None
    db.session.commit()
    flash("Pulled off the case. The paper is still in Records.", "info")
    if cid:
        return redirect(url_for("legal.case_detail", case_id=cid))
    return redirect(url_for("legal.detail", record_id=row.id))


@legal_bp.route("/cases/<int:case_id>/attach-record", methods=["POST"])
@login_required
@require_perm("legal")
def attach_record(case_id):
    case = scoped(LegalCase).filter_by(id=case_id).first_or_404()
    if not _can_edit(case):
        abort(403)
    try:
        rid = int(request.form.get("record_id") or 0)
    except (TypeError, ValueError):
        rid = 0
    rec = scoped(LegalRecord).filter_by(id=rid).first()
    if rec is None:
        flash("Pick a record.", "warning")
        return redirect(url_for("legal.case_detail", case_id=case.id))
    rec.case_id = case.id
    db.session.commit()
    flash(f"{KIND_LABELS.get(rec.kind, 'Record')} added to {case_label(case)}.", "success")
    return redirect(url_for("legal.case_detail", case_id=case.id))


@legal_bp.route("/cases/<int:case_id>/followup", methods=["POST"])
@login_required
@require_perm("legal")
def add_followup(case_id):
    case = scoped(LegalCase).filter_by(id=case_id).first_or_404()
    if not _can_edit(case):
        abort(403)
    kind = (request.form.get("kind") or "note").strip().lower()
    if kind not in FOLLOWUP_KINDS:
        kind = "note"
    title = (request.form.get("title") or "").strip()[:500] or None
    body = (request.form.get("body") or "").strip() or None
    url = (request.form.get("url") or "").strip()[:2000] or None
    extra = {}
    email_from = (request.form.get("email_from") or "").strip()[:200]
    if email_from:
        extra["email_from"] = email_from
    if kind == "link" and not url:
        flash("Paste a link.", "danger")
        return redirect(url_for("legal.case_detail", case_id=case.id))
    if kind == "note" and not (title or body):
        flash("Write a note.", "danger")
        return redirect(url_for("legal.case_detail", case_id=case.id))
    if kind == "email" and not (title or body or url):
        flash("Add the email subject, what it said, or a link to it.", "danger")
        return redirect(url_for("legal.case_detail", case_id=case.id))
    files = request.files.getlist("file") or []
    if kind == "file" and not any(getattr(f, "filename", None) for f in files):
        flash("Attach a photo, PDF, or email file.", "danger")
        return redirect(url_for("legal.case_detail", case_id=case.id))
    fu = LegalFollowup(
        household_id=case.household_id,
        case_id=case.id,
        kind=kind,
        title=title or (url if kind == "link" else None),
        body=body,
        url=url,
        extra_data=extra or None,
        created_by=current_user.id,
    )
    db.session.add(fu)
    db.session.flush()
    saved = 0
    for f in files:
        if save_legal_file(None, f, current_user.id, request.form.get("caption"), case=case, followup=fu):
            saved += 1
    if kind == "file" and not saved:
        db.session.delete(fu)
        db.session.commit()
        flash("That file didn't save. Try a photo or PDF.", "warning")
        return redirect(url_for("legal.case_detail", case_id=case.id))
    case.updated_at = datetime.utcnow()
    db.session.commit()
    flash("Follow-up on the case.", "success")
    return redirect(url_for("legal.case_detail", case_id=case.id))


@legal_bp.route("/followup/<int:followup_id>/delete", methods=["POST"])
@login_required
@require_perm("legal")
def delete_followup(followup_id):
    fu = scoped(LegalFollowup).filter_by(id=followup_id).first_or_404()
    case = scoped(LegalCase).filter_by(id=fu.case_id).first_or_404()
    if not _can_edit(case):
        abort(403)
    cid = case.id
    for f in list(fu.files or []):
        try:
            path = resolve_legal_file(f)
            path.unlink(missing_ok=True)
        except Exception:
            pass
        db.session.delete(f)
    db.session.delete(fu)
    db.session.commit()
    flash("Follow-up removed.", "info")
    return redirect(url_for("legal.case_detail", case_id=cid))


@legal_bp.route("/<int:record_id>")
@login_required
@require_perm("legal")
def detail(record_id):
    row = scoped(LegalRecord).options(joinedload(LegalRecord.case)).filter_by(id=record_id).first_or_404()
    author = User.query.filter_by(id=row.created_by).first() if row.created_by else None
    open_cases = (
        scoped(LegalCase)
        .filter_by(status="open")
        .order_by(LegalCase.number.desc())
        .limit(40)
        .all()
    )
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
        case_label=case_label,
        open_cases=open_cases,
        paper_files=_paper_files(row),
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
