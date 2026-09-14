"""Deliver a household reminder by email and/or calendar. Never crosses tenants."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.builddb.builddb import db
from app.builddb.table_households import Household
from app.builddb.table_reminders import Reminder
from app.builddb.table_users import User
from app.utils.calendar import (
    calendar_target,
    reminder_invite_ics,
    reminder_via,
    wants_calendar,
    wants_email,
)
from app.utils.mail import mail_config, send_mail

ADULT_ROLES = frozenset({"admin", "member"})


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _adults(household_id: int) -> list[User]:
    rows = User.query.filter_by(household_id=household_id, is_active=True).all()
    out = []
    for u in rows:
        role = (u.role or "").strip().lower()
        if role not in ADULT_ROLES and not bool(u.is_leader):
            continue
        out.append(u)
    return out


def _personal_via(user: User) -> str:
    return (getattr(user, "notify_via", None) or "both").strip().lower()


def announce_reminder(row: Reminder) -> None:
    """Push to each adult's chosen email calendar (auto) and/or email when due."""
    if row is None or not row.due_at:
        return
    push_calendar_invites(row)
    if row.due_at <= _utcnow() + timedelta(minutes=5):
        email_reminder(row)


def push_calendar_invites(row: Reminder) -> int:
    """METHOD:REQUEST to each adult on auto, addressed to *their* calendar email."""
    if row is None or (row.status or "open") != "open" or not row.due_at:
        return 0
    if getattr(row, "calendar_pushed_at", None):
        return 0
    household = Household.query.get(row.household_id)
    if household is None or not household.is_active:
        return 0
    if not wants_calendar(reminder_via(row, household)):
        return 0
    organizer = None
    try:
        from app.utils.household_mail import household_mail_config

        own = household_mail_config(household)
        if own and own.get("from_email"):
            organizer = own.get("from_email")
    except Exception:
        organizer = None
    if not organizer:
        organizer = (mail_config().get("from_email") or "").strip() or None
    sent = 0
    for person in _adults(row.household_id):
        personal = _personal_via(person)
        if personal in ("off", "email"):
            continue
        target = calendar_target(person)
        if not target["cal_auto"] or not target["cal_ready"]:
            continue
        ics = reminder_invite_ics(
            row, household, target["cal_email"], organizer_email=organizer
        ).encode("utf-8")
        when = row.due_at.strftime("%Y-%m-%d") if row.due_at else "soon"
        body = (
            f"Hi {person.name or person.username},\n\n"
            f"{row.title}\n"
            f"Due: {when}\n\n"
            f"This is on {target['cal_label']}. "
            "You do not add it by hand — that inbox's calendar should pick up the invite.\n"
        )
        ok, _msg = send_mail(
            target["cal_email"],
            f"{row.title} — on {target['cal_provider_label']}",
            body,
            ics=ics,
            ics_name="family-os.ics",
            ics_method="REQUEST",
            household=household,
        )
        if ok:
            sent += 1
    if sent:
        row.calendar_pushed_at = _utcnow()
        db.session.commit()
    return sent


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
    people = []
    for u in _adults(row.household_id):
        if _personal_via(u) in ("off", "calendar"):
            continue
        addr = (u.email or "").strip()
        if addr and "@" in addr:
            people.append(u)
    if not people:
        row.email_sent_at = _utcnow()
        db.session.commit()
        return
    when = row.due_at.strftime("%Y-%m-%d %H:%M") if row.due_at else "soon"
    subject = f"{row.title} — due {when}"
    any_ok = False
    for person in people:
        target = calendar_target(person)
        extra = ""
        if target["cal_auto"] and target["cal_ready"]:
            extra = f" Also on {target['cal_label']}."
        body = (
            f"Hi {person.name or person.username},\n\n"
            f"{row.title}\n"
            f"Due: {when}\n"
            f"Type: {row.type or 'reminder'}\n\n"
            "This is from your household on Family OS."
            f"{extra}\n"
        )
        ok, _msg = send_mail(person.email, subject, body, household=household)
        any_ok = any_ok or ok
    if any_ok or people:
        row.email_sent_at = _utcnow()
        db.session.commit()


def flush_due_emails(household_id: int) -> int:
    from sqlalchemy import and_, or_

    now = _utcnow()
    rows = (
        Reminder.query.filter_by(household_id=household_id, status="open")
        .filter(Reminder.due_at.isnot(None))
        .filter(
            or_(
                Reminder.calendar_pushed_at.is_(None),
                and_(Reminder.due_at <= now, Reminder.email_sent_at.is_(None)),
            )
        )
        .order_by(Reminder.due_at.asc())
        .limit(40)
        .all()
    )
    n = 0
    for row in rows:
        if not row.calendar_pushed_at:
            n += push_calendar_invites(row)
        if row.due_at <= now and not row.email_sent_at:
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


def announce_flash(user, row: Reminder | None) -> str:
    """Short line after logging maintenance / a reminder."""
    if row is None or not row.due_at:
        return ""
    target = calendar_target(user)
    when = row.due_at.strftime("%Y-%m-%d")
    if target["cal_auto"] and target["cal_ready"]:
        extra = " Email when it's due is on too." if _personal_via(user) in ("email", "both") else ""
        return f"{row.title} ({when}) goes to {target['cal_label']}.{extra}"
    if target["cal_auto"] and not target["cal_ready"]:
        return f"{row.title} is on Due ({when}). Set which email calendar on Look to auto-add it."
    return f"{row.title} is on Due ({when}). You're on manual — add it yourself, or switch to auto on Look."
