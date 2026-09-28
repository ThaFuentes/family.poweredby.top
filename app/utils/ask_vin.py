"""VIN-aware fluid-guide replies and explicitly confirmed saves for Ask."""
from __future__ import annotations

import re
from types import SimpleNamespace

from flask import has_request_context, session

from app.utils.vehicle_lookup import decode_vin, extract_vin

_PENDING_KEY = "family_ask_research_pending"
_LIVE_LOOKUP = re.compile(
    r"\b(?:search|google|research)\b.{0,30}\b(?:online|web|internet)\b"
    r"|\bsearch\s+online\b|\blook\s+(?:it\s+)?up\s+online\b",
    re.I,
)
_ACTION = re.compile(
    r"\b(?:add|log(?:ged)?|record(?:ed)?|change(?:d|s)?|replace(?:d)?|swap(?:ped)?|"
    r"pour(?:ed)?|fill(?:ed)?|topped\s+up|service(?:d)?|save|set|schedule|"
    r"remind(?:er|ers)?|due|overdue|past\s+due|last\s+(?:oil\s+)?change|did|just)\b",
    re.I,
)
_ENGINE_OIL_ASK = re.compile(
    r"\bviscosity\b|\b(?:engine|motor)\s+oil\b|"
    r"\bwhat(?:'s|\s+is)?\s+(?:(?:kind|type|weight)\s+of\s+)?oil\b(?!\s+filter)",
    re.I,
)
_OIL_FILTER_ASK = re.compile(r"\bwhat\s+oil\s+filter\b", re.I)
_QUESTION = re.compile(r"\b(?:what|which|does|do|need|needs|take|takes|use|uses|for)\b", re.I)
_OVERVIEW = re.compile(r"\b(?:what\s+)?(?:all\s+)?fluids?\b", re.I)
_EQUIPMENT_ASK = re.compile(
    r"\b(?:engine|cylinders?|fuel|transmission|drive|equipment)\b|\bwhat\s+does\s+this\s+vin\s+have\b",
    re.I,
)

_FLUID_FIELDS = (
    ("transmission", "Transmission"),
    ("transfer_case", "Transfer case"),
    ("rear_diff", "Rear differential"),
    ("front_diff", "Front differential"),
    ("coolant", "Coolant"),
    ("brake_fluid", "Brake fluid"),
    ("power_steering", "Power steering"),
)


def _household_vin(vin: str):
    """Exact VIN match; both joined rows are explicitly scoped to this household."""
    from app.builddb.table_vehicles import Vehicle
    from app.utils.ask import _find_items
    from app.utils.household import household_id

    hid = household_id()
    vehicle = Vehicle.query.filter_by(household_id=hid, vin=vin).first()
    if vehicle is None:
        return None
    rows = _find_items(str(vehicle.item_id), "vehicle", limit=1)
    return rows[0] if rows else None


def _decode(vin: str) -> dict | None:
    result = decode_vin(vin)
    if not isinstance(result, dict) or not result.get("ok"):
        return None
    facts = result.get("facts")
    if not isinstance(facts, dict) or not all(facts.get(k) for k in ("year", "make", "model")):
        return None
    return result


def _guide_item(facts: dict, name: str = ""):
    vehicle = SimpleNamespace(
        year=facts.get("year"), make=facts.get("make"), model=facts.get("model"),
        trim=facts.get("trim") or "", engine=facts.get("engine") or "",
        drive_type=facts.get("drive_type") or "",
    )
    return SimpleNamespace(
        id=0,
        name=name or " ".join(str(facts.get(k) or "") for k in ("year", "make", "model")).strip(),
        item_type="vehicle", notes="", category="vehicle", vehicle=vehicle, tool=None,
    )


def _drive_kind(value: str) -> str:
    text = re.sub(r"[^a-z0-9]", "", (value or "").lower())
    if text in {"4x2", "2wd", "rwd", "fwd", "2wheeldrive", "rearwheeldrive", "frontwheeldrive"}:
        return "2wd"
    if re.search(r"(?:4x4|4wd|4wheel|fourwheel|awd|allwheel)", text):
        return "4wd"
    return ""


def _engine_alternative(value: str, displacement: str) -> tuple[str, bool]:
    """Choose a slash-delimited guide half by its engine displacement tag."""
    text = str(value or "").strip()
    options = [part.strip() for part in text.split("/") if part.strip()]
    if len(options) < 2:
        return text, False
    if not displacement:
        return text, True
    try:
        target = float(str(displacement).lower().replace("l", "").strip())
    except (TypeError, ValueError):
        return text, True
    for option in options:
        for match in re.finditer(r"\b(\d+(?:\.\d+)?)\s*L\b", option, re.I):
            try:
                if abs(float(match.group(1)) - target) < 0.06:
                    return option, False
            except ValueError:
                continue
    return text, True


def _guide_values(item, facts: dict) -> tuple[dict, dict, bool]:
    from app.utils.fluid_specs import engine_oil_for, spec_for

    row = spec_for(item) or {}
    engine = dict(engine_oil_for(item) or {})
    uncertain = False
    for field in ("needs", "capacity", "filter"):
        if engine.get(field):
            engine[field], unsure = _engine_alternative(engine[field], str(facts.get("displacement_l") or ""))
            uncertain = uncertain or unsure
    drive = _drive_kind(str(facts.get("drive_type") or ""))
    fluids = {}
    for key, _label in _FLUID_FIELDS:
        spec = str(row.get(key) or "").strip()
        if not spec:
            continue
        if key in {"front_diff", "transfer_case"} and drive != "4wd":
            continue
        fluids[key] = spec
    return engine, fluids, uncertain


def _saved_item_for_sentence(text: str):
    from app.utils.ask import _oil_targets

    rows = _oil_targets(text)
    return rows[0] if len(rows) == 1 else None


def _typed_vin(text: str) -> str | None:
    """Find a VIN token inside a sentence without compacting the other words into it."""
    for match in re.finditer(r"(?<![A-HJ-NPR-Z0-9])[A-HJ-NPR-Z0-9]{17}(?![A-HJ-NPR-Z0-9])", text or "", re.I):
        vin = extract_vin(match.group(0))
        if vin:
            return vin
    # Preserve the decoder helper's support for wrapped VIN-only / door-tag input.
    return extract_vin(text) if len(re.sub(r"[^A-Za-z0-9]", "", text or "")) <= 19 else None


def _target(text: str) -> tuple[str, object | None, bool]:
    vin = _typed_vin(text)
    if vin:
        return vin, _household_vin(vin), True
    item = _saved_item_for_sentence(text)
    vehicle = getattr(item, "vehicle", None) if item is not None else None
    vin = (getattr(vehicle, "vin", "") or "").strip().upper() if vehicle else ""
    return (vin, item, False) if vin else ("", None, False)


def _facts_for(vin: str, item, explicit: bool) -> tuple[dict, dict | None]:
    decoded = _decode(vin)
    if decoded:
        return dict(decoded["facts"]), decoded
    if explicit or item is None or getattr(item, "vehicle", None) is None:
        return {}, None
    vehicle = item.vehicle
    facts = {
        key: getattr(vehicle, field, None)
        for key, field in (
            ("year", "year"), ("make", "make"), ("model", "model"),
            ("trim", "trim"), ("drive_type", "drive_type"), ("engine", "engine"),
            ("fuel_type", "fuel_type"), ("transmission", "transmission"),
        )
    }
    facts.update({"displacement_l": "", "cylinders": ""})
    return (facts, None) if all(facts.get(k) for k in ("year", "make", "model")) else ({}, None)


def _pending_save(vin: str, item, facts: dict, decoded: dict | None, engine: dict, fluids: dict) -> None:
    if not has_request_context():
        return
    fields = (
        "year", "make", "model", "trim", "drive_type", "fuel_type", "engine",
        "transmission", "displacement_l", "cylinders",
    )
    session[_PENDING_KEY] = {
        "source": "vin_builtin",
        "item_id": int(item.id) if item is not None and getattr(item, "id", None) else None,
        "name": (getattr(item, "name", "") if item is not None else "") or (decoded or {}).get("name") or " ".join(str(facts.get(k) or "") for k in ("year", "make", "model")).strip(),
        "vin": vin,
        "vehicle_facts": {key: facts[key] for key in fields if facts.get(key)},
        "fluids": dict(fluids),
        "engine": {key: engine[key] for key in ("needs", "capacity", "filter", "interval_miles", "interval_months", "interval_hours") if engine.get(key)},
    }
    session.pop("family_ask_oil_pending", None)


def _saved_answer(item, key: str) -> str | None:
    from app.utils.ask import _fluid_say, _item_card, _oil_fields
    from app.utils.oil import FLUID_LABELS, get_fluids

    fields = _oil_fields(item)
    card = _item_card(item)
    if key == "engine_oil" and (fields.get("needs") or fields.get("in_it")):
        label = "engine oil"
        spec = fields.get("needs") or fields.get("in_it")
        return f"{card.get('name') or 'Vehicle'} — {label}: {spec}" + (f" · {card.get('href')}" if card.get("href") else "")
    fluid_key = key
    fluids = get_fluids(item.vehicle)
    if fluid_key in fluids:
        return _fluid_say(item, FLUID_LABELS[fluid_key], fluids[fluid_key])
    return None


def vin_fluid_say(text: str) -> str | None:
    """Answer a VIN-backed guide question locally and stage saves until confirmation."""
    raw = (text or "").strip()
    if not raw or _LIVE_LOOKUP.search(raw) or _ACTION.search(raw):
        return None
    from app.utils.oil import fluid_asked

    key, _label = fluid_asked(raw)
    if not key:
        if _OIL_FILTER_ASK.search(raw):
            key = "oil_filter"
        elif _ENGINE_OIL_ASK.search(raw) and _QUESTION.search(raw):
            key = "engine_oil"
        elif _OVERVIEW.search(raw):
            key = "overview"
        elif _EQUIPMENT_ASK.search(raw) and _QUESTION.search(raw):
            key = "equipment"
        else:
            return None

    vin, item, explicit = _target(raw)
    if not vin:
        return None
    facts, decoded = _facts_for(vin, item, explicit)
    if not facts or (explicit and not decoded):
        return None

    # Existing household values win, including when an explicitly typed VIN picked
    # its own row and the older fluid handler did not recognize the sentence.
    if item is not None and getattr(item, "vehicle", None) is not None and key in {
        "engine_oil", "rear_diff", "front_diff", "transmission", "transfer_case",
        "coolant", "brake_fluid", "power_steering",
    }:
        saved = _saved_answer(item, key)
        if saved:
            return saved

    guide_item = _guide_item(facts, getattr(item, "name", "") if item is not None else "")
    from app.utils.fluid_specs import spec_for
    from app.utils.oil import FLUID_LABELS

    row = spec_for(guide_item)
    if not row:
        return None
    engine, fluids, uncertain = _guide_values(guide_item, facts)
    host = getattr(item, "vehicle", None) if item is not None else None
    if host is not None:
        from app.utils.oil import get_fluids

        saved_fluids = get_fluids(host)
        fluids = {field: value for field, value in fluids.items() if field not in saved_fluids}
        if getattr(host, "oil_needs", None) or getattr(host, "oil_type", None):
            engine = {}
    description = " ".join(str(facts.get(k) or "") for k in ("year", "make", "model") if facts.get(k))
    drive = str(facts.get("drive_type") or "").strip()
    decoded_intro = ""
    if explicit and item is None:
        engine_text = str(facts.get("engine") or "").strip()
        decoded_intro = f"This VIN decodes to {description}"
        if engine_text:
            decoded_intro += f", {engine_text}"
        decoded_intro += ". "

    if key == "engine_oil":
        if not engine.get("needs"):
            return None
        answer = f"Engine oil for {description}: {engine['needs']}"
        if engine.get("capacity"):
            answer += f", {engine['capacity']}"
        if engine.get("filter"):
            answer += f"; filter {engine['filter']}"
        if uncertain:
            answer += ". I couldn’t tell which engine from the VIN, so the guide lists both choices"
    elif key == "oil_filter":
        if not engine.get("filter"):
            return None
        answer = f"Oil filter for {description}: {engine['filter']}"
    elif key in FLUID_LABELS:
        label = FLUID_LABELS[key]
        if _drive_kind(drive) == "2wd" and key in {"front_diff", "transfer_case"}:
            answer = f"{label} for {description}: this VIN decodes as 2WD, so there is no {label.lower()} fluid service"
        elif row.get(key):
            answer = f"{label} for {description}: {row[key]}"
        else:
            return None
    elif key == "equipment":
        requested = {
            "engine": ("engine", "engine"),
            "cylinders": ("cylinders", "cylinders"),
            "fuel_type": ("fuel", "fuel"),
            "transmission": ("transmission", "transmission"),
            "drive_type": ("drive", "drive"),
        }
        details = []
        broad = bool(re.search(r"\bequipment\b|\bwhat\s+does\s+this\s+vin\s+have\b", raw, re.I))
        for fact, (term, label) in requested.items():
            if facts.get(fact) and (broad or re.search(rf"\b{term}\b", raw, re.I)):
                details.append(f"{label} {facts[fact]}")
        if re.search(r"\b(?:oil\s+)?filter\b", raw, re.I) and engine.get("filter"):
            details.append(f"oil filter {engine['filter']}")
        if not details:
            return None
        answer = f"For {description}: " + "; ".join(details)
    elif key == "overview":
        parts = []
        if engine.get("needs"):
            oil = engine["needs"]
            if engine.get("capacity"):
                oil += f", {engine['capacity']}"
            parts.append(f"engine oil {oil}")
        for fluid_key, label in _FLUID_FIELDS:
            if fluids.get(fluid_key) and fluid_key not in {"power_steering"}:
                parts.append(f"{label.lower()} {fluids[fluid_key]}")
        if not parts:
            return None
        answer = f"For {description}: " + "; ".join(parts)
        if uncertain:
            answer += ". I couldn’t tell which engine from the VIN, so the guide lists both capacity choices"
    else:
        return None

    answer = decoded_intro + answer
    if drive:
        answer += f". Drive: {drive}"
    answer += ". Built-in guide for this VIN."
    if item is not None and getattr(item, "id", None):
        answer += f" /items/{item.id}"
    # Stage the whole applicable built-in bundle: no database change occurs until
    # the existing yes / “save that” confirmation path invokes apply_pending_vin.
    _pending_save(vin, item, facts, decoded, engine, fluids)
    if has_request_context():
        answer += ' Say “save that” to allow me to put the VIN, engine, and applicable fluid specs on the truck.'
        return {"ok": True, "say": answer, "confirm": True, "did": [], "vault_locked": False}
    return answer


def apply_pending_vin(pending: dict) -> dict:
    """Save VIN details and the guide bundle only after Ask's explicit confirmation."""
    from flask_login import current_user

    from app.builddb.builddb import db
    from app.builddb.table_items import Item
    from app.builddb.table_vehicles import Vehicle
    from app.routes.items import can_create_type
    from app.utils.household import household_id
    from app.utils.permissions import can
    from app.utils.qr_labels import item_payload

    hid = household_id()
    vin = str(pending.get("vin") or "").strip().upper()
    if not vin or extract_vin(vin) != vin:
        return {"ok": False, "say": "That VIN is not valid. Nothing was saved.", "did": [], "vault_locked": False}
    if not (can("maintain") or can("edit_meta")):
        return {"ok": False, "say": "You cannot update that vehicle or its fluid specs.", "did": [], "vault_locked": False}

    item_id = pending.get("item_id")
    if item_id:
        item = (
            Item.query.filter_by(id=int(item_id), household_id=hid, item_type="vehicle")
            .filter(Item.removed_at.is_(None)).first()
        )
        if item is None:
            return {"ok": False, "say": "That vehicle is no longer in this household. Nothing was saved.", "did": [], "vault_locked": False}
    else:
        item = (
            Item.query.join(Vehicle, Vehicle.item_id == Item.id)
            .filter(
                Item.household_id == hid, Item.item_type == "vehicle",
                Item.removed_at.is_(None), Vehicle.household_id == hid, Vehicle.vin == vin,
            ).first()
        )
        if item is None:
            if not (can("maintain") or can("edit_meta")):
                return {"ok": False, "say": "You cannot add vehicles, so I did not save that VIN.", "did": [], "vault_locked": False}
            if not can_create_type("vehicle"):
                return {"ok": False, "say": "You cannot add vehicles, so I did not save that VIN.", "did": [], "vault_locked": False}
            facts = pending.get("vehicle_facts") if isinstance(pending.get("vehicle_facts"), dict) else {}
            name = pending.get("name") or " ".join(str(facts.get(k) or "") for k in ("year", "make", "model")).strip() or f"VIN {vin[:8]}"
            item = Item(household_id=hid, name=str(name)[:200], item_type="vehicle", created_by=current_user.id)
            db.session.add(item)
            db.session.flush()
            item.barcode = item_payload(hid, item.id)
            vehicle = Vehicle(item_id=item.id, household_id=hid)
            db.session.add(vehicle)
            _fill_vehicle(vehicle, facts)
            vehicle.vin = vin
            db.session.flush()

    vehicle = getattr(item, "vehicle", None)
    if vehicle is None or int(getattr(vehicle, "household_id", 0) or 0) != hid:
        db.session.rollback()
        return {"ok": False, "say": "That vehicle is not in this household.", "did": [], "vault_locked": False}
    existing_vin = (getattr(vehicle, "vin", None) or "").strip().upper()
    if existing_vin and existing_vin != vin:
        return {"ok": False, "say": "That vehicle now has a different VIN saved. I left it unchanged.", "did": [], "vault_locked": False}
    vehicle.vin = vin
    facts = pending.get("vehicle_facts") if isinstance(pending.get("vehicle_facts"), dict) else {}
    _fill_vehicle(vehicle, facts)
    extra = dict(vehicle.extra_data) if isinstance(vehicle.extra_data, dict) else {}
    extra["vin_decode"] = dict(facts)
    vehicle.extra_data = extra
    db.session.flush()

    fluids = pending.get("fluids") if isinstance(pending.get("fluids"), dict) else {}
    engine = pending.get("engine") if isinstance(pending.get("engine"), dict) else {}
    payload = {"item": str(item.id), "confirmed": True}
    if fluids:
        payload["fluids"] = fluids
    if engine.get("needs"):
        payload.update({key: engine[key] for key in (
            "needs", "capacity", "filter", "interval_miles", "interval_months", "interval_hours",
        ) if engine.get(key)})
    if len(payload) > 2:
        from app.utils.ask_do import tool_oil_save

        result = tool_oil_save(payload)
        if not result.get("ok"):
            db.session.rollback()
            return {"ok": False, "say": result.get("error") or result.get("hint") or "I couldn’t save those vehicle specs.", "did": [], "vault_locked": False}
    else:
        db.session.commit()
        result = {"ok": True}
    saved = []
    if engine.get("needs"):
        saved.append("engine oil")
    saved.extend(key.replace("_", " ") for key in fluids)
    what = ", ".join(saved) or "vehicle details"
    href = result.get("href") or f"/items/{item.id}"
    return {"ok": True, "say": f"Saved the VIN and {what} on {item.name}. {href}", "did": ["vin"], "vault_locked": False}


def _fill_vehicle(vehicle, facts: dict) -> None:
    for field, limit in (
        ("year", 4), ("make", 80), ("model", 80), ("trim", 80),
        ("drive_type", 80), ("fuel_type", 80), ("engine", 160), ("transmission", 80),
    ):
        value = facts.get(field)
        if not value or getattr(vehicle, field, None):
            continue
        if field == "year":
            try:
                value = int(str(value)[:4])
            except (TypeError, ValueError):
                continue
        else:
            value = str(value)[:limit]
        setattr(vehicle, field, value)
