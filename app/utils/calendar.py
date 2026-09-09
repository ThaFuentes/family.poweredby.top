"""Household calendar feed. Token is per person; events are that household only."""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone

from app.builddb.builddb import db
from app.builddb.table_households import Household
from app.builddb.table_reminders import Reminder
from app.builddb.table_users import User

NOTIFY_CHOICES = ("email", "calendar", "both")


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalize_via(value: str | None, default: str = "both") -> str:
    v = (value or "").strip().lower()
    return v if v in NOTIFY_CHOICES else default


def wants_email(via: str) -> bool:
    return normalize_via(via) in ("email", "both")


def wants_calendar(via: str) -> bool:
    return normalize_via(via) in ("calendar", "both")


def household_reminders_via(household: Household | None) -> str:
    extra = getattr(household, "settings_json", None) or {}
    if not isinstance(extra, dict):
        extra = {}
    return normalize_via(extra.get("reminders_via"), "both")


def set_household_reminders_via(household: Household, via: str) -> None:
    extra = household.settings_json if isinstance(household.settings_json, dict) else {}
    extra = dict(extra)
    extra["reminders_via"] = normalize_via(via)
    household.settings_json = extra
    db.session.commit()


def reminder_via(row: Reminder, household: Household | None = None) -> str:
    if row and (row.notify_via or "").strip():
        return normalize_via(row.notify_via)
    return household_reminders_via(household)


def ensure_calendar_token(user: User) -> str:
    token = (getattr(user, "calendar_token", None) or "").strip()
    if token:
        return token
    token = secrets.token_urlsafe(24)
    user.calendar_token = token
    db.session.commit()
    return token


def rotate_calendar_token(user: User) -> str:
    user.calendar_token = secrets.token_urlsafe(24)
    db.session.commit()
    return user.calendar_token


def user_for_calendar_token(token: str) -> User | None:
    token = (token or "").strip()
    if not token or len(token) < 16:
        return None
    user = User.query.filter_by(calendar_token=token, is_active=True).first()
    if user is None:
        return None
    household = getattr(user, "household", None)
    if household is not None and not bool(getattr(household, "is_active", True)):
        return None
    return user


def _ics_escape(text: str) -> str:
    return (
        (text or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    if len(line) <= 75:
        return line
    out = [line[:75]]
    rest = line[75:]
    while rest:
        out.append(" " + rest[:74])
        rest = rest[74:]
    return "\r\n".join(out)


def _fmt(dt: datetime) -> str:
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _rrule(recurrence: str | None) -> str | None:
    raw = (recurrence or "").strip().lower()
    m = re.fullmatch(r"(\d+)\s*d", raw)
    if m:
        return f"RRULE:FREQ=DAILY;INTERVAL={int(m.group(1))}"
    m = re.fullmatch(r"(\d+)\s*w", raw)
    if m:
        return f"RRULE:FREQ=WEEKLY;INTERVAL={int(m.group(1))}"
    m = re.fullmatch(r"(\d+)\s*m", raw)
    if m:
        return f"RRULE:FREQ=MONTHLY;INTERVAL={int(m.group(1))}"
    return None


def vevent(row: Reminder, household_name: str = "") -> str | None:
    if not row or not row.due_at:
        return None
    start = row.due_at
    end = start + timedelta(hours=1)
    uid = f"family-rem-{row.id}@family.poweredby.top"
    summary = _ics_escape(row.title or "Reminder")
    desc = _ics_escape(row.notes or row.type or "Family OS reminder")
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{_fmt(_utcnow())}",
        f"DTSTART:{_fmt(start)}",
        f"DTEND:{_fmt(end)}",
        f"SUMMARY:{summary}",
        f"DESCRIPTION:{desc}",
        "STATUS:CONFIRMED",
    ]
    rrule = _rrule(row.recurrence)
    if rrule:
        lines.append(rrule)
    if household_name:
        lines.append(f"LOCATION:{_ics_escape(household_name)}")
    lines.extend(
        [
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            "DESCRIPTION:Due",
            "TRIGGER:-P1D",
            "END:VALARM",
            "END:VEVENT",
        ]
    )
    return "\r\n".join(_fold(x) for x in lines)


def household_ics(household: Household, rows: list[Reminder], method: str = "PUBLISH") -> str:
    name = getattr(household, "name", None) or "Family OS"
    events = []
    for row in rows:
        if (row.status or "open") != "open":
            continue
        if not wants_calendar(reminder_via(row, household)):
            continue
        block = vevent(row, name)
        if block:
            events.append(block)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Family OS//Reminders//EN",
        "CALSCALE:GREGORIAN",
        f"METHOD:{method}",
        f"X-WR-CALNAME:Family OS · {_ics_escape(name)}",
    ]
    body = "\r\n".join(_fold(x) for x in lines)
    if events:
        body += "\r\n" + "\r\n".join(events)
    body += "\r\nEND:VCALENDAR\r\n"
    return body


def reminder_ics(row: Reminder, household: Household, method: str = "REQUEST") -> str:
    return household_ics(household, [row], method=method)
