"""Household places — a short shared vocabulary, not a floor plan."""
from __future__ import annotations

from sqlalchemy.orm.attributes import flag_modified

from app.builddb.builddb import db

DEFAULT_PLACES = (
    "Fridge",
    "Freezer",
    "Pantry",
    "Bathroom",
    "Junk drawer",
    "Garage",
    "Laundry",
    "Hall closet",
    "Driveway",
)


def _norm(raw: str) -> str:
    return " ".join((raw or "").strip().split())[:80]


def list_places(household) -> list[str]:
    settings = household.settings_json if isinstance(getattr(household, "settings_json", None), dict) else {}
    raw = settings.get("places") if isinstance(settings, dict) else None
    out = []
    seen = set()
    for item in raw if isinstance(raw, list) else DEFAULT_PLACES:
        name = _norm(str(item))
        key = name.lower()
        if not name or key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out or list(DEFAULT_PLACES)


_PLACE_WORDS = (
    ("Fridge", ("fridge", "refrigerator", "cooler", "cold")),
    ("Freezer", ("freezer", "ice")),
    ("Pantry", ("pantry", "cupboard", "cabinet", "shelf", "dry")),
    ("Bathroom", ("bathroom", "bath", "toilet", "shower")),
    ("Junk drawer", ("junk", "drawer", "odds")),
    ("Garage", ("garage", "workshop", "shed")),
    ("Laundry", ("laundry", "washer", "dryer")),
    ("Hall closet", ("closet", "linen", "hall")),
    ("Driveway", ("driveway", "car", "vehicle", "outside")),
)


def snap_location(hint, household=None) -> str | None:
    """Map an AI/heuristic hint onto this house's place names."""
    raw = " ".join(str(hint or "").strip().split())
    if not raw or raw.lower() in ("null", "none", "n/a", "-"):
        return None
    places = list_places(household) if household is not None else list(DEFAULT_PLACES)
    low = raw.lower()
    for p in places:
        pl = p.lower()
        if pl == low or pl in low or low in pl:
            return p
    for label, words in _PLACE_WORDS:
        if any(w in low for w in words):
            for p in places:
                if any(w in p.lower() for w in words) or p.lower() == label.lower():
                    return p
            return label if label in places else raw[:80]
    return raw[:80]


def save_places(household, raw) -> list[str]:
    if isinstance(raw, str):
        bits = raw.replace(",", "\n").splitlines()
    elif isinstance(raw, (list, tuple)):
        bits = list(raw)
    else:
        bits = []
    names = []
    seen = set()
    for bit in bits:
        name = _norm(str(bit))
        key = name.lower()
        if not name or key in seen:
            continue
        seen.add(key)
        names.append(name)
    if not names:
        names = list(DEFAULT_PLACES)
    settings = dict(household.settings_json or {}) if isinstance(household.settings_json, dict) else {}
    settings["places"] = names[:40]
    household.settings_json = settings
    flag_modified(household, "settings_json")
    db.session.add(household)
    return names


def rooms_map(g) -> dict:
    """Place → count. Falls back to default_location × quantity."""
    from decimal import Decimal, InvalidOperation

    def n(v):
        try:
            d = Decimal(str(v))
        except (InvalidOperation, ValueError, TypeError):
            return Decimal("0")
        return d if d > 0 else Decimal("0")

    extra = g.extra_data if g is not None and isinstance(g.extra_data, dict) else {}
    raw = extra.get("rooms") if isinstance(extra, dict) else None
    out = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            name = _norm(str(k))
            q = n(v)
            if name and q > 0:
                out[name] = q
    if out:
        return out
    loc = _norm(getattr(g, "default_location", None) or "") if g is not None else ""
    q = n(getattr(g, "quantity", 0) if g is not None else 0)
    if loc and q > 0:
        return {loc: q}
    return {}


def sync_rooms(g, rooms: dict):
    """Write rooms, quantity = sum, default_location = the room with the most."""
    from decimal import Decimal
    from sqlalchemy.orm.attributes import flag_modified as _flag

    from app.utils.scan import set_quantity

    cleaned = {}
    total = Decimal("0")
    for k, v in (rooms or {}).items():
        name = _norm(str(k))
        try:
            q = Decimal(str(v))
        except Exception:
            q = Decimal("0")
        if not name or q <= 0:
            continue
        cleaned[name] = q
        total += q
    extra = dict(g.extra_data or {}) if isinstance(g.extra_data, dict) else {}
    extra["rooms"] = {k: float(v) for k, v in cleaned.items()}
    g.extra_data = extra
    try:
        _flag(g, "extra_data")
    except Exception:
        pass
    set_quantity(g, total)
    g.default_location = max(cleaned, key=lambda p: cleaned[p]) if cleaned else (g.default_location or None)
    return total


def bump_room(g, place: str, delta) -> None:
    from decimal import Decimal

    place = _norm(place)
    if not place:
        return
    rooms = rooms_map(g)
    try:
        d = Decimal(str(delta))
    except Exception:
        d = Decimal("0")
    cur = rooms.get(place, Decimal("0"))
    nxt = cur + d
    if nxt <= 0:
        rooms.pop(place, None)
    else:
        rooms[place] = nxt
    sync_rooms(g, rooms)


def take_from_rooms(g, amount) -> None:
    from decimal import Decimal

    try:
        left = Decimal(str(amount))
    except Exception:
        left = Decimal("1")
    if left <= 0:
        return
    rooms = rooms_map(g)
    if not rooms:
        from app.utils.scan import set_quantity, clamp_qty

        set_quantity(g, max(Decimal("0"), clamp_qty(g.quantity) - left))
        return
    for name in sorted(rooms, key=lambda n: rooms[n], reverse=True):
        if left <= 0:
            break
        take = rooms[name] if rooms[name] < left else left
        rooms[name] -= take
        left -= take
        if rooms[name] <= 0:
            rooms.pop(name, None)
    sync_rooms(g, rooms)


def remember_upc(household, barcode: str, meta: dict) -> None:
    code = (barcode or "").strip()
    if not code or not isinstance(meta, dict):
        return
    settings = dict(household.settings_json or {}) if isinstance(household.settings_json, dict) else {}
    blob = dict(settings.get("upc_memory") or {}) if isinstance(settings.get("upc_memory"), dict) else {}
    keep = {k: meta[k] for k in ("kind", "item_type", "linked_item_id", "location", "name") if meta.get(k) not in (None, "")}
    if not keep:
        return
    blob[code[:80]] = keep
    if len(blob) > 400:
        blob = dict(list(blob.items())[-400:])
    settings["upc_memory"] = blob
    household.settings_json = settings
    flag_modified(household, "settings_json")


def recall_upc(household, barcode: str) -> dict | None:
    code = (barcode or "").strip()
    if not code:
        return None
    settings = household.settings_json if isinstance(getattr(household, "settings_json", None), dict) else {}
    blob = settings.get("upc_memory") if isinstance(settings, dict) else None
    if not isinstance(blob, dict):
        return None
    hit = blob.get(code)
    return dict(hit) if isinstance(hit, dict) else None
