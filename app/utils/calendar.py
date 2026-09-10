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


def _fmt_utc(dt: datetime) -> str:
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _fmt_local(dt: datetime) -> str:
    """Floating local time — datetime-local from the phone, not UTC."""
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt.strftime("%Y%m%dT%H%M%S")


def _fmt_date(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")


def _is_all_day(dt: datetime) -> bool:
    return dt.hour == 0 and dt.minute == 0 and dt.second == 0


def _rrule(recurrence: str | None) -> str | None:
    """Map household 'how often' onto RFC 5545. Miles/hours stay in Family OS only."""
    raw = (recurrence or "").strip().lower()
    named = {
        "30d": "RRULE:FREQ=MONTHLY;INTERVAL=1",
        "90d": "RRULE:FREQ=MONTHLY;INTERVAL=3",
        "180d": "RRULE:FREQ=MONTHLY;INTERVAL=6",
        "365d": "RRULE:FREQ=YEARLY;INTERVAL=1",
    }
    if raw in named:
        return named[raw]
    if raw.endswith("mi") or raw.endswith("h"):
        return None
    m = re.fullmatch(r"(\d+)\s*d", raw)
    if m:
        n = int(m.group(1))
        if n == 7:
            return "RRULE:FREQ=WEEKLY;INTERVAL=1"
        if n % 365 == 0:
            return f"RRULE:FREQ=YEARLY;INTERVAL={n // 365}"
        if n % 30 == 0:
            return f"RRULE:FREQ=MONTHLY;INTERVAL={n // 30}"
        return f"RRULE:FREQ=DAILY;INTERVAL={n}"
    m = re.fullmatch(r"(\d+)\s*w", raw)
    if m:
        return f"RRULE:FREQ=WEEKLY;INTERVAL={int(m.group(1))}"
    m = re.fullmatch(r"(\d+)\s*m", raw)
    if m:
        return f"RRULE:FREQ=MONTHLY;INTERVAL={int(m.group(1))}"
    return None


def subscribe_links(https_url: str, name: str = "Family OS") -> dict:
    """Deep links Apple / Google / Outlook understand. Feed itself is the https ICS URL."""
    from urllib.parse import quote, urlsplit, urlunsplit

    url = (https_url or "").strip()
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    local = host in ("127.0.0.1", "localhost", "::1")
    if parts.scheme in ("http", "https"):
        feed_scheme = "http" if local and parts.scheme == "http" else "https"
        https = urlunsplit((feed_scheme, parts.netloc, parts.path, parts.query, parts.fragment))
        webcal = urlunsplit(("webcal", parts.netloc, parts.path, parts.query, parts.fragment))
    else:
        https = url
        webcal = url.replace("https://", "webcal://", 1).replace("http://", "webcal://", 1)
    label = (name or "Family OS")[:80]
    enc_https = quote(https, safe="")
    enc_name = quote(label, safe="")
    return {
        "https": https,
        "webcal": webcal,
        "apple": webcal,
        "google": f"https://calendar.google.com/calendar/render?cid={enc_https}",
        "outlook": f"https://outlook.live.com/calendar/0/addfromweb?url={enc_https}&name={enc_name}",
        "outlook_office": f"https://outlook.office.com/calendar/0/addfromweb?url={enc_https}&name={enc_name}",
        "name": label,
    }


def vevent(row: Reminder, household_name: str = "") -> str | None:
    if not row or not row.due_at:
        return None
    start = row.due_at
    uid = f"family-rem-{row.id}@family.poweredby.top"
    summary = _ics_escape(row.title or "Reminder")
    bits = [row.notes or "", row.type or "", "Family OS reminder"]
    rec = (row.recurrence or "").strip()
    if rec.endswith("mi"):
        bits.append("Repeats by mileage in Family OS — your calendar shows this due date.")
    elif rec.endswith("h"):
        bits.append("Repeats by hours in Family OS — your calendar shows this due date.")
    desc = _ics_escape(" · ".join(b for b in bits if b))
    stamp = _fmt_utc(getattr(row, "updated_at", None) or _utcnow())
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{_fmt_utc(_utcnow())}",
        f"LAST-MODIFIED:{stamp}",
        f"SUMMARY:{summary}",
        f"DESCRIPTION:{desc}",
        "STATUS:CONFIRMED",
        "TRANSP:TRANSPARENT",
        "SEQUENCE:0",
    ]
    if _is_all_day(start):
        day = start.date()
        nxt = day + timedelta(days=1)
        lines.insert(3, f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}")
        lines.insert(4, f"DTEND;VALUE=DATE:{nxt.strftime('%Y%m%d')}")
    else:
        end = start + timedelta(hours=1)
        lines.insert(3, f"DTSTART:{_fmt_local(start)}")
        lines.insert(4, f"DTEND:{_fmt_local(end)}")
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


def member_subscribe(user: User, household: Household | None, feed_url: str) -> dict:
    """Per-person Apple / Google / Outlook links. Secret feed is this member's token."""
    house_name = getattr(household, "name", None) or "Family OS"
    who = (getattr(user, "name", None) or getattr(user, "username", None) or "You").split()[0]
    links = subscribe_links(feed_url, f"Family OS · {house_name}")
    links["who"] = who
    links["house"] = house_name
    return links


def household_ics(
    household: Household,
    rows: list[Reminder],
    method: str = "PUBLISH",
    *,
    member_feed: bool = False,
) -> str:
    name = getattr(household, "name", None) or "Family OS"
    events = []
    for row in rows:
        if (row.status or "open") != "open":
            continue
        if not member_feed and not wants_calendar(reminder_via(row, household)):
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
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        "X-PUBLISHED-TTL:PT1H",
        f"NAME:Family OS · {_ics_escape(name)}",
        f"X-WR-CALNAME:Family OS · {_ics_escape(name)}",
        "X-WR-CALDESC:Oil, filters, blades — this household only.",
    ]
    chunks = [_fold(x) for x in lines]
    if events:
        chunks.extend(events)
    chunks.append("END:VCALENDAR")
    return "\r\n".join(chunks) + "\r\n"


def reminder_ics(row: Reminder, household: Household, method: str = "PUBLISH") -> str:
    return household_ics(household, [row], method=method)
