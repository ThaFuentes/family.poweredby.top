"""Household-English labels for reminder type and how often."""

REMINDER_TYPES = (
    ("bill", "Bill"),
    ("oil_change", "Oil change"),
    ("filter", "Filter"),
    ("blades", "Blades"),
    ("hvac_filter", "HVAC filter"),
    ("tires", "Tires"),
    ("battery", "Battery"),
    ("smoke", "Smoke / CO"),
    ("custom", "Something else"),
)

RECURRENCE = (
    ("", "One time"),
    ("30d", "Every month"),
    ("90d", "Every 3 months"),
    ("180d", "Every 6 months"),
    ("365d", "Every year"),
    ("3000mi", "Every 3,000 miles"),
    ("5000mi", "Every 5,000 miles"),
    ("50h", "Every 50 hours"),
)

_TYPE_MAP = {k: v for k, v in REMINDER_TYPES}
_REC_MAP = {k: v for k, v in RECURRENCE}


def type_label(raw: str | None) -> str:
    key = (raw or "").strip()
    if key in _TYPE_MAP:
        return _TYPE_MAP[key]
    return (raw or "Reminder").replace("_", " ")


def recurrence_label(raw: str | None) -> str:
    key = (raw or "").strip()
    if not key:
        return "One time"
    if key in _REC_MAP:
        return _REC_MAP[key]
    if key.endswith("d") and key[:-1].isdigit():
        n = int(key[:-1])
        if n == 30:
            return "Every month"
        if n % 30 == 0:
            return f"Every {n // 30} months"
        return f"Every {n} days"
    if key.endswith("mi") and key[:-2].isdigit():
        return f"Every {int(key[:-2]):,} miles"
    if key.endswith("h") and key[:-1].isdigit():
        return f"Every {key[:-1]} hours"
    return key


def parse_recurrence(raw: str | None) -> str | None:
    key = (raw or "").strip()
    if not key:
        return None
    allowed = {k for k, _ in RECURRENCE if k}
    return key if key in allowed else None
