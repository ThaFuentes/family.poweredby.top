"""A log line updates the living record it belongs to.

The **log** is a history row in ``item_logs``. The **living record** is the
vehicle or tool row the screens actually show: odometer, hours, the oil columns
on the Oil sheet, the fluids object, and maintenance history.

``add_item_log`` in :mod:`app.utils.item_log` calls :func:`apply_log_to_record`
once for every new row, so the Log form, Ask's ``tool_log_save``, trip start and
the maintenance form all leave the same fingerprint without a second copy of
this logic.

House rules baked in here:

* A blank field never clears a saved value, and a log never wipes a field.
* An older log never rolls the odometer back, and never rewrites a newer oil
  change.
* Only a repair writes a ``MaintenanceRecord``.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime

from app.utils.oil import (
    fields_from_text,
    fluid_key,
    save_item_oil,
    set_fluid,
)

# Kinds that carry an odometer / hours reading onto the living record.
_READING_KINDS = ("miles", "hours", "fillup", "repair", "code", "trip")

# A real oil *service*. The bare word "oil" is not enough: "oil spec", "oil
# leak" and "oil filter" (no change verb) must not move the oil record.
_OIL_CHANGE_RE = re.compile(
    r"oil\s+change"
    r"|changed\s+the\s+oil"
    r"|oil\s+(?:and|&)\s+filter"
    r"|engine\s+oil\s+service",
    re.I,
)

# A grade the Oil sheet should show, e.g. 5W-30 / 0W-20 / SAE 30.
_GRADE_RE = re.compile(r"\b(\d{1,2}\s*W-?\s*\d{2}|SAE\s*\d{2})\b", re.I)

# Gear-oil / engine-oil weights (75W-90, 5W-30) used to spot a fluid spec.
_WEIGHT_RE = re.compile(r"\b\d{1,2}\s*W-?\s*\d{2}\b", re.I)

# A filter number: letters and digits, at least four characters (PH8A, 90915-YZZD2).
_FILTER_RE = re.compile(
    r"\bfilter\b[^A-Za-z0-9]{0,12}([A-Za-z0-9][A-Za-z0-9-]{3,})", re.I
)
_TOKEN_RE = re.compile(r"\b[A-Za-z0-9][A-Za-z0-9-]{3,}\b")
_DIGIT_RE = re.compile(r"\d")
_SPEC_WORDS_RE = re.compile(r"\bspec\b|\bfluid\b|\boil\b", re.I)

# Note titles that carry a grade into oil_needs instead of the log only.
_GRADE_TITLES = ("oil spec", "oil needs", "oil type")

# Incoming kind aliases for an oil service. Stored kind stays "repair".
OIL_KINDS = ("oil", "oil_change", "oil-change")

_MAINTENANCE_TYPE_CAP = 80


def is_oil_kind(kind) -> bool:
    """True when an incoming kind means "oil change" (no LOG_KINDS entry)."""
    return str(kind or "").strip().lower() in OIL_KINDS


def map_log_kind(kind, title=None):
    """Normalize the kind ``add_item_log`` is about to store.

    Returns ``(kind, title, service)``. An oil service becomes a ``repair`` with
    ``service == "oil"`` so the stored row kind stays inside ``LOG_KINDS`` and no
    new ``item_logs.kind`` value is needed.
    """
    raw = str(kind or "note").strip().lower()
    service = None
    if raw in OIL_KINDS:
        raw = "repair"
        service = "oil"
        if not str(title or "").strip():
            title = "Oil change"
    return raw, title, service


def is_oil_change(row) -> bool:
    """Is this log row an oil service?"""
    extra = _get(row, "extra_data")
    if isinstance(extra, dict) and str(extra.get("service") or "").strip().lower() == "oil":
        return True
    blob = _blob(row)
    return bool(_OIL_CHANGE_RE.search(blob))


def maintenance_fields(item, row, is_oil_change_service: bool):
    """Pure check: the ``MaintenanceRecord`` fields this log should insert, or None.

    None when the row is not a repair, or its ``maintenance_id`` is already set
    (the maintenance form already owns that record).
    """
    if str(_get(row, "kind") or "").strip().lower() != "repair":
        return None
    if _get(row, "maintenance_id"):
        return None
    title = str(_get(row, "title") or "").strip()
    if is_oil_change_service:
        mtype = "oil_change"
    else:
        mtype = title or "repair"
    when = _as_date(_get(row, "happened_on")) or date.today()
    return {
        "household_id": _get(item, "household_id"),
        "parent_type": _get(item, "item_type"),
        "parent_id": _get(item, "id"),
        "type": mtype[:_MAINTENANCE_TYPE_CAP],
        "date": when,
        "mileage_or_hours": _get(row, "reading"),
        "notes": _get(row, "notes"),
        "created_by": _get(row, "created_by"),
    }


def apply_log_to_record(item, row) -> None:
    """Write one log row onto the item's vehicle / tool row. Never raises."""
    try:
        kind = str(_get(row, "kind") or "note").strip().lower()
        host, is_vehicle = _host(item)
        oil_change = is_oil_change(row)

        if host is not None and kind in _READING_KINDS:
            _raise_reading(host, is_vehicle, row)

        if kind == "repair":
            if oil_change:
                if host is not None and oil_log_is_newer(host, row):
                    _write_oil(item, host, is_vehicle, row)
                    _touch_tool_maintenance(host, is_vehicle, row)
            elif host is not None:
                _write_fluid(host, row)
                _touch_tool_maintenance(host, is_vehicle, row)
            _insert_maintenance(item, row, oil_change)
            return

        if kind == "note":
            _write_note(host, row)
    except Exception:
        # A history row must never take the log write down with it. Log it
        # (never ascii-encode) so a broken write-through is visible, not silent.
        logging.getLogger(__name__).exception(
            "apply_log_to_record failed for item %s log %s",
            _get(item, "id"),
            _get(row, "id"),
        )
        return


# --------------------------------------------------------------------------- #
# reading (odometer / hours)
# --------------------------------------------------------------------------- #

def _raise_reading(host, is_vehicle: bool, row) -> None:
    new = _num(_get(row, "reading"))
    if new is None:
        return
    if is_vehicle:
        saved = _num(_get(host, "current_mileage"))
        if saved is None or new >= saved:
            host.current_mileage = int(new)
    else:
        saved = _num(_get(host, "hours_used"))
        if saved is None or new >= saved:
            host.hours_used = new


# --------------------------------------------------------------------------- #
# oil
# --------------------------------------------------------------------------- #

def oil_log_is_newer(host, row) -> bool:
    """May this log move the saved oil record? Newer wins; equal needs a reading."""
    date_attr = _last_date_attr(host)
    if date_attr is None:
        return True
    saved = _as_date(_get(host, date_attr))
    if saved is None:
        return True
    new = _as_date(_get(row, "happened_on"))
    if new is None:
        # An undated log must not move a record that already has a date.
        return False
    if new != saved:
        return new > saved
    read_attr = _last_read_attr(host)
    saved_read = _num(_get(host, read_attr)) if read_attr else None
    if saved_read is None:
        return True
    new_read = _num(_get(row, "reading"))
    return new_read is not None and new_read >= saved_read


def _write_oil(item, host, is_vehicle: bool, row) -> None:
    payload = _oil_payload(is_vehicle, row)
    if not payload:
        return
    try:
        save_item_oil(item, payload)
    except Exception:
        # A house item has no vehicle/tool oil record. Skip it, never raise.
        return


def _oil_payload(is_vehicle: bool, row) -> dict:
    blob = _blob(row)
    payload: dict = {}
    when = _as_date(_get(row, "happened_on"))
    if when is not None:
        payload["last_date"] = when.isoformat()
    reading = _get(row, "reading")
    if reading is not None:
        if is_vehicle:
            payload["last_miles"] = reading
        else:
            payload["last_hours"] = reading
    # needs carries a real grade only. fields_from_text would copy the whole
    # sentence whenever it sees the word "oil"; that must not reach oil_needs.
    if _GRADE_RE.search(blob):
        phrase = _grade_phrase(blob)
        if phrase:
            payload["needs"] = phrase
    parsed = fields_from_text(blob) or {}
    for key in ("capacity", "interval_miles", "interval_months", "interval_hours"):
        value = parsed.get(key)
        if value not in (None, ""):
            payload[key] = value
    filt = _filter_number(blob)
    if filt:
        payload["filter"] = filt
    return payload


def _last_date_attr(host):
    if hasattr(host, "last_oil_change_date"):
        return "last_oil_change_date"
    if hasattr(host, "last_oil_date"):
        return "last_oil_date"
    return None


def _last_read_attr(host):
    if hasattr(host, "last_oil_change_mileage"):
        return "last_oil_change_mileage"
    if hasattr(host, "last_oil_hours"):
        return "last_oil_hours"
    return None


# --------------------------------------------------------------------------- #
# fluids (rear diff, transmission, coolant…)
# --------------------------------------------------------------------------- #

def fluid_key_for(text) -> str:
    """``fluid_key`` without letting a weight mask the fluid's name.

    ``fluid_key`` treats any ``NNw-NN`` as engine oil, so ``rear diff 75W-90``
    would come back empty. Strip the weight and try again; a rear diff or a
    transmission still names itself.
    """
    raw = text or ""
    key = fluid_key(raw)
    if key:
        return key
    stripped = _WEIGHT_RE.sub(" ", raw)
    if stripped != raw:
        return fluid_key(stripped)
    return ""


def fluid_spec_phrase(text):
    """The spec phrase for a saved fluid, or None. Never the whole note."""
    raw = str(text or "").strip()
    if not raw:
        return None
    match = _WEIGHT_RE.search(raw)
    if match:
        return _phrase(raw, match.start(), match.end())
    if _SPEC_WORDS_RE.search(raw) and _DIGIT_RE.search(raw):
        return " ".join(raw.split())[:200]
    return None


def _write_fluid(host, row) -> None:
    blob = _blob(row)
    key = fluid_key_for(blob)
    if not key:
        return
    spec = fluid_spec_phrase(blob)
    if not spec:
        return
    try:
        set_fluid(host, key, spec)
    except Exception:
        return


# --------------------------------------------------------------------------- #
# notes
# --------------------------------------------------------------------------- #

def _write_note(host, row) -> None:
    """Only an oil-spec note writes to the record; every other note stays a log line."""
    if host is None:
        return
    title = str(_get(row, "title") or "").strip().lower()
    if title not in _GRADE_TITLES:
        return
    phrase = _grade_phrase(_get(row, "notes"))
    if phrase:
        host.oil_needs = phrase[:200]


# --------------------------------------------------------------------------- #
# maintenance history
# --------------------------------------------------------------------------- #

def _touch_tool_maintenance(host, is_vehicle: bool, row) -> None:
    if is_vehicle or host is None:
        return
    when = _as_date(_get(row, "happened_on"))
    if when is None:
        return
    saved = _as_date(_get(host, "last_maintenance_at"))
    if saved is not None and when <= saved:
        return
    host.last_maintenance_at = datetime(when.year, when.month, when.day)


def _insert_maintenance(item, row, is_oil_change_service: bool) -> None:
    fields = maintenance_fields(item, row, is_oil_change_service)
    if not fields:
        return
    from app.builddb.builddb import db
    from app.builddb.table_maintenance_records import MaintenanceRecord

    rec = MaintenanceRecord(**fields)
    db.session.add(rec)
    db.session.flush()
    row.maintenance_id = rec.id


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #

def _get(obj, name, default=None):
    return getattr(obj, name, default)


def _blob(row) -> str:
    return " ".join(
        str(part) for part in (_get(row, "title"), _get(row, "notes")) if part
    )


def _host(item):
    """The living vehicle/tool row and whether it is a vehicle."""
    vehicle = _get(item, "vehicle")
    if vehicle is not None:
        return vehicle, True
    tool = _get(item, "tool")
    if tool is not None:
        return tool, False
    return None, False


def _as_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()[:10]
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _num(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _phrase(text, start: int, end: int, *, before: int = 40, after: int = 80, cap: int = 200) -> str:
    text = str(text or "")
    left = max(0, start - before)
    right = min(len(text), end + after)
    return " ".join(text[left:right].split())[:cap]


def _grade_phrase(text):
    raw = str(text or "")
    match = _GRADE_RE.search(raw)
    if not match:
        return None
    return _phrase(raw, match.start(), match.end())


def _has_alpha_digit(token: str) -> bool:
    return bool(re.search(r"[A-Za-z]", token)) and bool(re.search(r"\d", token))


def _filter_number(text):
    """A filter part number (PH8A, 90915-YZZD2) or None. Never invented."""
    raw = str(text or "")
    if not raw:
        return None
    match = _FILTER_RE.search(raw)
    if match and _has_alpha_digit(match.group(1)):
        return match.group(1)[:80]
    for token in _TOKEN_RE.findall(raw):
        if _GRADE_RE.fullmatch(token):
            continue
        if _has_alpha_digit(token):
            return token[:80]
    return None
