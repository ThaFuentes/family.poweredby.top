"""Oil the machine needs, what is in it, and when the next change is due.

Also the other fluids (rear diff, transmission, coolant…): they live in the
vehicle/tool extra_data JSON under key "fluids" — no migration needed — because
the oil_needs column is engine oil only.
"""
from __future__ import annotations

import calendar
import re
from datetime import date, datetime


def _text(value, cap: int) -> str:
    return ("" if value is None else str(value)).strip()[:cap]


def _blank(value) -> bool:
    return value is None or str(value).strip() == ""


def add_months(day: date, months: int) -> date:
    months = int(months)
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last))


def _date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value, 32)
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _int(value):
    text = _text(value, 20).replace(",", "")
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _put(record, attr: str, raw, *, clear: bool, kind: str, cap: int = 200):
    if raw is None and not clear:
        return
    if _blank(raw):
        if clear:
            setattr(record, attr, None)
        return
    if kind == "date":
        parsed = _date(raw)
        if parsed or clear:
            setattr(record, attr, parsed)
        return
    if kind == "int":
        parsed = _int(raw)
        if parsed is None:
            if clear:
                setattr(record, attr, None)
            return
        setattr(record, attr, parsed)
        return
    setattr(record, attr, _text(raw, cap) or None)


# Non-engine fluids. The oil_needs / oil_type columns are ENGINE oil only.
# Keys are canonical; phrases map to them in fluid_key().
FLUID_LABELS: dict[str, str] = {
    "rear_diff": "Rear differential",
    "front_diff": "Front differential",
    "transmission": "Transmission",
    "transfer_case": "Transfer case",
    "coolant": "Coolant",
    "brake_fluid": "Brake fluid",
    "power_steering": "Power steering",
}

# Order matters: the front patterns run before the rear ones so "front diff" never
# lands on rear_diff. A bare "diff"/"gear oil" is the rear axle by default — that is
# what people mean by it on a truck. Keep this the ONLY place a phrase becomes a key;
# ask.py asks fluid_key() instead of keeping a second copy of these words.
_FLUID_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    (
        "front_diff",
        re.compile(
            r"\bfront\s*(?:dif{1,2}(?:erential)?|axle|end)\b"
            r"|\bfront\b.{0,14}\bgear\s*oil\b"
            r"|\bfront\s+end\b.{0,14}\b(?:oil|fluid|fluid\b)",
            re.I,
        ),
    ),
    (
        "rear_diff",
        re.compile(
            r"\brear\s*(?:dif{1,2}(?:erential)?|axle|end)\b"
            r"|\bback\s*end\b"
            r"|\brear\b.{0,14}\bgear\s*oil\b"
            r"|\bgear\s*(?:oil|fluid)\b"
            r"|\bring\s*(?:and|&)\s*pinion\b"
            r"|\baxle\s*(?:oil|fluid|lube|grease)\b"
            # Bare "dif"/"diff"/"differential" — the common case (and "dif" with one
            # f is how people actually type it). Runs last on purpose.
            r"|\bdif{1,2}(?:erential)?\b",
            re.I,
        ),
    ),
    ("transfer_case", re.compile(r"\btransfer\s*case\b|\b4wd\s+fluid\b|\bfour.?wheel.?drive\s+fluid\b", re.I)),
    ("transmission", re.compile(r"\btrans(?:mission|axle)?\b|\batf\b|\btrans\s*(?:fluid|oil)\b", re.I)),
    ("coolant", re.compile(r"\bcoolant\b|\bantifreeze\b|\bradiator\s*fluid\b", re.I)),
    ("brake_fluid", re.compile(r"\bbrake\s*fluid\b", re.I)),
    ("power_steering", re.compile(r"\bpower\s*steering\b(?:\s*fluid)?", re.I)),
)


def fluid_key(phrase: str) -> str:
    """"rear diff" / "gear oil in the back end" … → canonical fluid key. Empty when engine oil."""
    raw = (phrase or "").strip().lower()
    if not raw or re.search(r"\b(?:engine|motor)\s+oil\b|\b\d{1,2}\s*w-\s*\d{2}\b", raw):
        return ""
    for key, pat in _FLUID_PATTERNS:
        if pat.search(raw):
            return key
    return ""


def fluid_label(key: str) -> str:
    """'rear_diff' → 'Rear differential'. Falls back to a tidied-up key."""
    return FLUID_LABELS.get((key or "").strip(), (key or "").replace("_", " ").title())


def fluid_asked(phrase: str) -> tuple[str, str]:
    """(key, label) for a non-engine fluid ask. ("", "") for engine oil or no match.

    Every caller goes through here so a "what fluid" question can never be mistaken
    for an engine-oil question (or the other way round).
    """
    key = fluid_key(phrase)
    return (key, fluid_label(key)) if key else ("", "")


def get_fluids(host) -> dict:
    """Saved non-engine fluid specs: {"rear_diff": "75W-90 GL-5", …}."""
    extra = getattr(host, "extra_data", None)
    if not isinstance(extra, dict):
        return {}
    fluids = extra.get("fluids")
    if not isinstance(fluids, dict):
        return {}
    return {k: str(v or "").strip()[:200] for k, v in fluids.items() if str(v or "").strip() and k in FLUID_LABELS}


def set_fluid(host, key: str, value: str) -> bool:
    """Save one fluid spec into extra_data. Empty value clears it."""
    key = (key or "").strip()
    if key not in FLUID_LABELS:
        return False
    extra = dict(host.extra_data) if isinstance(host.extra_data, dict) else {}
    fluids = dict(extra.get("fluids")) if isinstance(extra.get("fluids"), dict) else {}
    text = str(value or "").strip()[:200]
    if text:
        fluids[key] = text
    else:
        fluids.pop(key, None)
    extra["fluids"] = fluids
    # Reassign (not mutate in place) so ORM change detection picks it up.
    host.extra_data = extra
    return True


def apply_fluids_payload(host, data: dict) -> list[str]:
    """Write fluid specs from an oil_save payload. Returns the keys saved."""
    data = data or {}
    saved = []
    single = data.get("fluid") or data.get("fluid_key")
    if single:
        key = fluid_key(str(single)) or str(single).strip().lower().replace(" ", "_")
        value = data.get("value") or data.get("spec") or data.get("needs") or ""
        if set_fluid(host, key, str(value)):
            saved.append(key)
    many = data.get("fluids")
    if isinstance(many, dict):
        for name, value in many.items():
            key = fluid_key(str(name)) or str(name).strip().lower().replace(" ", "_")
            if set_fluid(host, key, str(value or "")):
                saved.append(key)
    return saved


def fluid_payload_has_fields(data: dict) -> bool:
    data = data or {}
    if data.get("fluid") or data.get("fluids"):
        return True
    for key in FLUID_LABELS:
        if not _blank(data.get(key)):
            return True
    return False


def apply_vehicle_oil(vehicle, data: dict, *, clear: bool = False) -> None:
    """Set the oil record. Blank fields stay put unless clear is true."""
    data = data or {}
    _put(vehicle, "oil_needs", data.get("needs", data.get("oil_needs")), clear=clear, kind="text", cap=200)
    _put(vehicle, "oil_capacity", data.get("capacity", data.get("oil_capacity")), clear=clear, kind="text", cap=40)
    _put(vehicle, "oil_type", data.get("in_it", data.get("oil_type")), clear=clear, kind="text", cap=80)
    _put(vehicle, "filter_type", data.get("filter", data.get("filter_type")), clear=clear, kind="text", cap=80)
    _put(vehicle, "last_oil_change_date", data.get("last_date", data.get("last_oil_change_date")), clear=clear, kind="date")
    _put(vehicle, "last_oil_change_mileage", data.get("last_miles", data.get("last_oil_change_mileage")), clear=clear, kind="int")
    _put(vehicle, "oil_interval_miles", data.get("interval_miles", data.get("oil_interval_miles")), clear=clear, kind="int")
    _put(vehicle, "oil_interval_months", data.get("interval_months", data.get("oil_interval_months")), clear=clear, kind="int")
    next_date = data.get("next_date", data.get("next_oil_due_date"))
    next_miles = data.get("next_miles", data.get("next_oil_due_mileage"))
    if not _blank(next_date):
        _put(vehicle, "next_oil_due_date", next_date, clear=clear, kind="date")
    elif vehicle.last_oil_change_date and vehicle.oil_interval_months:
        vehicle.next_oil_due_date = add_months(vehicle.last_oil_change_date, vehicle.oil_interval_months)
    elif clear and ("next_date" in data or "next_oil_due_date" in data):
        vehicle.next_oil_due_date = None
    if not _blank(next_miles):
        _put(vehicle, "next_oil_due_mileage", next_miles, clear=clear, kind="int")
    elif vehicle.last_oil_change_mileage is not None and vehicle.oil_interval_miles:
        vehicle.next_oil_due_mileage = int(vehicle.last_oil_change_mileage) + int(vehicle.oil_interval_miles)
    elif clear and ("next_miles" in data or "next_oil_due_mileage" in data):
        vehicle.next_oil_due_mileage = None


def apply_tool_oil(tool, data: dict, *, clear: bool = False) -> None:
    data = data or {}
    _put(tool, "oil_needs", data.get("needs", data.get("oil_needs")), clear=clear, kind="text", cap=200)
    _put(tool, "oil_capacity", data.get("capacity", data.get("oil_capacity")), clear=clear, kind="text", cap=40)
    _put(tool, "oil_type", data.get("in_it", data.get("oil_type")), clear=clear, kind="text", cap=80)
    _put(tool, "last_oil_date", data.get("last_date", data.get("last_oil_date")), clear=clear, kind="date")
    _put(tool, "last_oil_hours", data.get("last_hours", data.get("last_oil_hours")), clear=clear, kind="int")
    _put(tool, "oil_interval_hours", data.get("interval_hours", data.get("oil_interval_hours")), clear=clear, kind="int")
    _put(tool, "oil_interval_months", data.get("interval_months", data.get("oil_interval_months")), clear=clear, kind="int")
    next_date = data.get("next_date", data.get("next_oil_due_date"))
    next_hours = data.get("next_hours", data.get("next_oil_due_hours"))
    if not _blank(next_date):
        _put(tool, "next_oil_due_date", next_date, clear=clear, kind="date")
    elif tool.last_oil_date and tool.oil_interval_months:
        tool.next_oil_due_date = add_months(tool.last_oil_date, tool.oil_interval_months)
    elif clear and ("next_date" in data or "next_oil_due_date" in data):
        tool.next_oil_due_date = None
    if not _blank(next_hours):
        _put(tool, "next_oil_due_hours", next_hours, clear=clear, kind="int")
    elif tool.last_oil_hours is not None and tool.oil_interval_hours:
        tool.next_oil_due_hours = int(tool.last_oil_hours) + int(tool.oil_interval_hours)
    elif clear and ("next_hours" in data or "next_oil_due_hours" in data):
        tool.next_oil_due_hours = None


_CAP = re.compile(r"(\d+(?:\.\d+)?)\s*(quarts?|qts?|qt|ounces?|oz|liters?|litres?|l)\b", re.I)
_EVERY_MI = re.compile(r"every\s+([\d,]+)\s*(?:miles|mi)\b", re.I)
_EVERY_MO = re.compile(r"every\s+(\d{1,2})\s*months?\b", re.I)
_EVERY_HR = re.compile(r"every\s+([\d,]+)\s*hours?\b", re.I)
_AT_MI = re.compile(r"(?:at|@)\s+([\d,]{2,})\b|\b([\d,]{4,})\s*(?:miles|mi)\b", re.I)
_DAY = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")


def fields_from_text(text: str) -> dict:
    """Pull oil form values out of a sentence Ask already said."""
    raw = (text or "").strip()
    if not raw:
        return {}
    out = {}
    spec = _OIL_SPEC.search(raw) if "_OIL_SPEC" in globals() else None
    # local pattern so this module does not depend on ask.py
    spec = re.search(r"\b(\d{1,2}\s*W-\s*\d{2}|SAE\s*\d{2})\b", raw, re.I)
    if spec:
        start = max(0, spec.start() - 50)
        end = min(len(raw), spec.end() + 70)
        out["needs"] = " ".join(raw[start:end].split())[:200]
    elif re.search(r"\boil\b", raw, re.I):
        out["needs"] = " ".join(raw.split())[:200]
    cap = _CAP.search(raw)
    if cap:
        unit = cap.group(2).lower()
        short = {"quarts": "qt", "quart": "qt", "qts": "qt", "ounces": "oz", "ounce": "oz", "liters": "L", "liter": "L", "litres": "L", "litre": "L"}.get(unit, unit)
        out["capacity"] = f"{cap.group(1)} {short}"
    miles = _EVERY_MI.search(raw)
    if miles:
        out["interval_miles"] = miles.group(1).replace(",", "")
    months = _EVERY_MO.search(raw)
    if months:
        out["interval_months"] = months.group(1)
    hours = _EVERY_HR.search(raw)
    if hours:
        out["interval_hours"] = hours.group(1).replace(",", "")
    day = _DAY.search(raw)
    if day:
        out["last_date"] = day.group(1)
    at = _AT_MI.search(raw)
    if at:
        out["last_miles"] = (at.group(1) or at.group(2) or "").replace(",", "")
    return out


def normalize_oil_payload(data: dict | None, extra_text: str = "") -> dict:
    src = dict(data or {})
    # A fluids-only payload (rear_diff / transmission / …) is complete as-is:
    # never mine the conversation for engine-oil fields, or plan sentences
    # like “I'll save the oil spec on…” end up in needs.
    _engine_hints = (
        "needs", "oil_needs", "oil", "spec", "capacity", "oil_capacity",
        "in_it", "oil_type", "filter", "filter_type", "last_date", "last_miles",
        "last_hours", "interval_miles", "interval_months", "interval_hours",
        "next_date", "next_miles", "next_hours",
    )
    if fluid_payload_has_fields(src) and all(_blank(src.get(k)) for k in _engine_hints):
        return src
    needs = src.get("needs") or src.get("oil_needs") or src.get("oil") or src.get("spec") or ""
    if _blank(needs):
        for key in ("text", "body", "reply", "answer", "details", "kind"):
            if not _blank(src.get(key)):
                needs = src.get(key)
                break
    parsed = fields_from_text(str(needs or ""))
    if not parsed and extra_text:
        parsed = fields_from_text(extra_text)
    if parsed.get("needs"):
        src["needs"] = parsed["needs"]
    elif not _blank(needs):
        src["needs"] = _text(needs, 200)
    for key in ("capacity", "interval_miles", "interval_months", "interval_hours", "last_date", "last_miles"):
        if _blank(src.get(key)) and parsed.get(key):
            src[key] = parsed[key]
    return src


def oil_payload_has_fields(data: dict) -> bool:
    keys = (
        "needs",
        "oil_needs",
        "capacity",
        "oil_capacity",
        "in_it",
        "oil_type",
        "filter",
        "filter_type",
        "last_date",
        "last_miles",
        "last_hours",
        "interval_miles",
        "interval_months",
        "interval_hours",
        "next_date",
        "next_miles",
        "next_hours",
    )
    return any(not _blank(data.get(k)) for k in keys) or fluid_payload_has_fields(data)


def save_item_oil(item, data: dict, *, clear: bool = False) -> str:
    if getattr(item, "vehicle", None) is not None:
        apply_vehicle_oil(item.vehicle, data, clear=clear)
        return "vehicle"
    if getattr(item, "tool", None) is not None:
        apply_tool_oil(item.tool, data, clear=clear)
        return "tool"
    raise ValueError("no oil record")
