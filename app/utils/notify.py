"""Deliver a household reminder by email and/or calendar. Never crosses tenants."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.builddb.builddb import db
from app.builddb.table_households import Household
from app.builddb.table_reminders import Reminder
from app.builddb.table_users import User
from app.utils.calendar import reminder_ics, reminder_via, wants_email
from app.utils.mail import send_mail

ADULT_ROLES = frozenset({"admin", "member"})


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _recipients(household_id: int) -> list[User]:
    rows = User.query.filter_by(household_id=household_id, is_active=True).all()
    out = []
    for u in rows:
        role = (u.role or "").strip().lower()
        if role not in ADULT_ROLES and not bool(u.is_leader):
            continue
        if not (u.email or "").strip():
            continue
        personal = (getattr(u, "notify_via", None) or "both").strip().lower()
        if personal in ("off", "calendar"):
            continue
        out.append(u)
    return out


def announce_reminder(row: Reminder) -> None:
    """Email now if the reminder is already due; otherwise calendar feed covers the wait."""
    if row is None:
        return
    due = row.due_at
    if due is None:
        return
    if due <= _utcnow() + timedelta(minutes=5):
        email_reminder(row)


def email_reminder(row: Reminder) -> None:
    if row is None or (row.status or "open") != "open":
        return
    if row.email_sent_at:
        return
    household = Household.query.get(row.household_id)
    if household is None or not household.is_active:
        return
    if not wants_email(reminder_via(row, household)):
        return
    people = _recipients(row.household_id)
    if not people:
        row.email_sent_at = _utcnow()
        db.session.commit()
        return
    when = row.due_at.strftime("%Y-%m-%d %H:%M") if row.due_at else "soon"
    subject = f"{row.title} — due {when}"
    body = (
        f"{row.title}\n"
        f"Due: {when}\n"
        f"Type: {row.type or 'reminder'}\n\n"
        "This is from your household on Family OS. The attached .ics is this one due date "
        "(opens in Apple Calendar, Google Calendar, Outlook, or Gmail). "
        "For a live calendar that stays in sync, subscribe on the Due page.\n"
    )
    ics = reminder_ics(row, household).encode("utf-8")
    any_ok = False
    for person in people:
        ok, _msg = send_mail(
            person.email,
            subject,
            f"Hi {person.name or person.username},\n\n{body}",
            ics=ics,
            ics_name="family-reminder.ics",
        )
        any_ok = any_ok or ok
    if any_ok or people:
        row.email_sent_at = _utcnow()
        db.session.commit()


def flush_due_emails(household_id: int) -> int:
    now = _utcnow()
    rows = (
        Reminder.query.filter_by(household_id=household_id, status="open")
        .filter(Reminder.due_at.isnot(None), Reminder.due_at <= now)
        .filter(Reminder.email_sent_at.is_(None))
        .all()
    )
    n = 0
    for row in rows:
        email_reminder(row)
        n += 1
    return n


def maybe_flush_due_emails(household_id: int, *, ttl: int = 60) -> int:
    """Home used to SMTP-scan on every load. Once a minute per house is enough."""
    from app.utils.hot_cache import get as cache_get, put as cache_put

    key = f"flush:{int(household_id)}"
    if cache_get(key) is not None:
        return 0
    n = flush_due_emails(household_id)
    cache_put(key, 1, ttl)
    return n
