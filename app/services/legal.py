"""Records (legal papers), cases and follow-ups shared by the Records page and Maya."""
from __future__ import annotations

from datetime import datetime

from app.builddb.builddb import db

RECORD_KEYS = ("title", "kind", "status", "agency", "case_number", "location",
               "issued_on", "due_on", "amount", "body", "outcome", "kind_detail")


def form_record(form, row=None):
    """(fields, error). The Records page form, as a plain mapping."""
    from app.routes.legal import _kind, _parse_amount, _parse_date, _status

    title = (form.get("title") or "").strip()
    if not title:
        return None, "Say what it is — parking ticket, code notice, whatever they handed you."
    kind = _kind(form.get("kind"), row.kind if row else "citation")
    status = _status(form.get("status"), row.status if row else "open")
    extra = {}
    if row is not None and isinstance(getattr(row, "extra_data", None), dict):
        extra = dict(row.extra_data)
    detail = (form.get("kind_detail") or "").strip()[:200]
    if detail:
        extra["kind_detail"] = detail
    else:
        extra.pop("kind_detail", None)
    return {
        "title": title[:500],
        "kind": kind,
        "status": status,
        "agency": (form.get("agency") or "").strip()[:400] or None,
        "case_number": (form.get("case_number") or "").strip()[:120] or None,
        "location": (form.get("location") or "").strip()[:400] or None,
        "issued_on": _parse_date(form.get("issued_on")),
        "due_on": _parse_date(form.get("due_on")),
        "amount": _parse_amount(form.get("amount")),
        "body": (form.get("body") or "").strip() or None,
        "outcome": (form.get("outcome") or "").strip() or None,
        "extra_data": extra or None,
    }, None


def record_form_values(row) -> dict:
    """What the edit form shows now, so a partial update keeps the rest."""
    extra = row.extra_data if isinstance(row.extra_data, dict) else {}

    def d(v):
        return v.strftime("%Y-%m-%d") if v else ""

    return {
        "title": row.title or "", "kind": row.kind or "", "status": row.status or "",
        "agency": row.agency or "", "case_number": row.case_number or "",
        "location": row.location or "", "issued_on": d(row.issued_on), "due_on": d(row.due_on),
        "amount": str(row.amount) if row.amount is not None else "", "body": row.body or "",
        "outcome": row.outcome or "", "kind_detail": extra.get("kind_detail") or "",
    }


def create_record(*, hid: int, user_id: int, fields: dict):
    from app.builddb.table_legal_records import LegalRecord

    row = LegalRecord(household_id=hid, created_by=user_id, **fields)
    db.session.add(row)
    db.session.flush()
    return row


def update_record(row, fields: dict):
    for key, val in fields.items():
        setattr(row, key, val)
    row.updated_at = datetime.utcnow()


def remove_record(row, *, actor_id, via="ui"):
    """Recycle bin: the record, its file rows and files (archived, not deleted)."""
    from app.builddb.table_legal_files import LegalFile
    from app.builddb.table_legal_records import LegalRecord
    from app.utils import maya_store

    files = LegalFile.query.filter_by(household_id=row.household_id, record_id=row.id).all()
    return maya_store.trash(
        hid=row.household_id,
        label=f"Record: {row.title or row.id}",
        rows=[(LegalRecord, row)] + [(LegalFile, f) for f in files],
        files=[f.stored_path for f in files if f.stored_path],
        actor_id=actor_id,
        via=via,
    )


def remove_followup(row, *, actor_id, via="ui"):
    from app.builddb.table_legal_files import LegalFile
    from app.builddb.table_legal_followups import LegalFollowup
    from app.utils import maya_store

    files = LegalFile.query.filter_by(household_id=row.household_id, followup_id=row.id).all()
    return maya_store.trash(
        hid=row.household_id,
        label=f"Follow-up: {row.title or row.kind}",
        rows=[(LegalFollowup, row)] + [(LegalFile, f) for f in files],
        files=[f.stored_path for f in files if f.stored_path],
        actor_id=actor_id,
        via=via,
    )


def open_case(*, hid: int, user_id: int, title, summary=None, record=None):
    """(case, error). New case, optionally tying a loose record to it."""
    from app.builddb.table_legal_cases import LegalCase, next_case_number

    title = (title or "").strip()
    if not title:
        return None, "Name the case."
    case = LegalCase(
        household_id=hid,
        number=next_case_number(hid),
        title=title[:500],
        status="open",
        summary=(summary or "").strip() or None,
        created_by=user_id,
    )
    db.session.add(case)
    db.session.flush()
    if record is not None and not record.case_id:
        record.case_id = case.id
    return case, None


def edit_case(case, data) -> None:
    from app.builddb.table_legal_cases import CASE_STATUSES

    title = (data.get("title") or "").strip()
    if title:
        case.title = title[:500]
    st = (data.get("status") or "").strip().lower()
    if st in CASE_STATUSES:
        case.status = st
    if "summary" in data:
        case.summary = (data.get("summary") or "").strip() or None
    case.updated_at = datetime.utcnow()


def add_followup(case, *, user_id: int, kind, title=None, body=None, url=None, email_from=None):
    """(followup, error). Same rules as the case page."""
    from app.builddb.table_legal_followups import FOLLOWUP_KINDS, LegalFollowup

    kind = (kind or "note").strip().lower()
    if kind not in FOLLOWUP_KINDS:
        kind = "note"
    title = (title or "").strip()[:500] or None
    body = (body or "").strip() or None
    url = (url or "").strip()[:2000] or None
    extra = {}
    if email_from:
        extra["email_from"] = str(email_from).strip()[:200]
    if kind == "link" and not url:
        return None, "Paste a link."
    if kind == "note" and not (title or body):
        return None, "Write a note."
    if kind == "email" and not (title or body or url):
        return None, "Add the email subject, what it said, or a link to it."
    fu = LegalFollowup(
        household_id=case.household_id,
        case_id=case.id,
        kind=kind,
        title=title or (url if kind == "link" else None),
        body=body,
        url=url,
        extra_data=extra or None,
        created_by=user_id,
    )
    db.session.add(fu)
    db.session.flush()
    case.updated_at = datetime.utcnow()
    return fu, None
