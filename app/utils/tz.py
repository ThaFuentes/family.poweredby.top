"""Household clock. Reminder instants are stored as naive UTC."""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TZ = "America/Chicago"
NAIVE_WARNING = "naive_due_at_assumed_household_tz"


class DueParse:
    def __init__(self, utc, warnings, tz_name, error=None):
        self.utc = utc
        self.warnings = list(warnings or [])
        self.tz = tz_name
        self.error = error


def zone(name: str | None):
    raw = (name or "").strip() or DEFAULT_TZ
    try:
        return ZoneInfo(raw), raw
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return ZoneInfo(DEFAULT_TZ), DEFAULT_TZ


def tz_for_household_id(hid) -> str:
    if not hid:
        return DEFAULT_TZ
    try:
        from app.builddb.table_households import Household

        row = Household.query.get(int(hid))
    except Exception:
        return DEFAULT_TZ
    return zone(getattr(row, "timezone", None) if row is not None else None)[1]


def _as_utc(stored):
    if stored is None:
        return None
    if getattr(stored, "tzinfo", None) is None:
        return stored.replace(tzinfo=timezone.utc)
    return stored.astimezone(timezone.utc)


def local_dt(stored, hh_tz=None):
    aware = _as_utc(stored)
    if aware is None:
        return None
    zi, _name = zone(hh_tz)
    return aware.astimezone(zi)


def utc_z(stored) -> str | None:
    aware = _as_utc(stored)
    if aware is None:
        return None
    return aware.strftime("%Y-%m-%dT%H:%M:%SZ")


def local_iso(stored, hh_tz=None) -> str | None:
    local = local_dt(stored, hh_tz)
    if local is None:
        return None
    return local.isoformat(timespec="seconds")


def local_date(stored, hh_tz=None):
    local = local_dt(stored, hh_tz)
    return local.date() if local is not None else None


def format_local(stored, hh_tz=None) -> str:
    local = local_dt(stored, hh_tz)
    if local is None:
        return ""
    return local.strftime("%Y-%m-%d %H:%M")


def format_local_clock(stored, hh_tz=None) -> str:
    local = local_dt(stored, hh_tz)
    if local is None:
        return "soon"
    return local.strftime("%Y-%m-%d %H:%M %Z")


def clock_fields(stored, hh_tz=None, warnings=None) -> dict:
    _zi, name = zone(hh_tz)
    out = {
        "due_at": utc_z(stored),
        "due_local": local_iso(stored, name),
        "tz": name,
    }
    if warnings:
        out["warnings"] = list(warnings)
    return out


def _date_only(text: str):
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        try:
            return datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def _combine_local(day, zi) -> datetime:
    local = datetime.combine(day, time(9, 0), tzinfo=zi)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def parse_due(raw, hh_tz=None, *, strict: bool = False) -> DueParse:
    """Turn a due value into naive UTC.

    An aware ISO value (Z or an offset) is converted to UTC.
    A naive value is read in the household zone. strict=True refuses that.
    A date alone means 09:00 in the household zone.
    """
    zi, tz_name = zone(hh_tz)
    if raw is None:
        return DueParse(None, [], tz_name)
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            if strict:
                return DueParse(None, [], tz_name, "naive")
            utc = raw.replace(tzinfo=zi).astimezone(timezone.utc).replace(tzinfo=None)
            return DueParse(utc, [NAIVE_WARNING], tz_name)
        utc = raw.astimezone(timezone.utc).replace(tzinfo=None)
        return DueParse(utc, [], tz_name)
    if isinstance(raw, date):
        return DueParse(_combine_local(raw, zi), [], tz_name)

    text = str(raw).strip()
    if not text:
        return DueParse(None, [], tz_name)
    day = _date_only(text)
    if day is not None:
        return DueParse(_combine_local(day, zi), [], tz_name)
    if len(text) == 10:
        return DueParse(None, [], tz_name, "bad")
    iso_text = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        parsed = datetime.fromisoformat(iso_text)
    except ValueError:
        return DueParse(None, [], tz_name, "bad")
    if parsed.tzinfo is None:
        if strict:
            return DueParse(None, [], tz_name, "naive")
        utc = parsed.replace(tzinfo=zi).astimezone(timezone.utc).replace(tzinfo=None)
        return DueParse(utc, [NAIVE_WARNING], tz_name)
    utc = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return DueParse(utc, [], tz_name)


def due_problem(parsed) -> tuple[str, str] | None:
    """Bot-facing error for a DueParse, or None when the value can be stored."""
    if parsed is None or not parsed.error:
        return None
    if parsed.error == "naive":
        return ("due_at needs a time zone. Send Z or an offset.", "naive_due_at")
    return ("due_at must be a date-time.", "bad_request")


def calendar_day(raw):
    """The calendar date written by the caller. A log date, not a zoned instant."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    text = str(raw).strip()
    if len(text) < 10:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
