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
