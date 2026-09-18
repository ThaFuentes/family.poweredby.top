"""Guess what a scanned UPC actually is.

Catalogs lie: Open Food Facts is food-first, so a car battery can come back
blank or weird. Heuristics first; household AI refines when a key is present.
"""
from __future__ import annotations

from typing import Any

KIND_LABELS = {
    "food": "Food",
    "drink": "Drink",
    "household": "Household",
    "pet": "Pet",
    "beauty": "Personal care",
    "aa_battery": "Household battery",
    "car_battery": "Car battery",
    "motor_oil": "Motor oil",
    "filter": "Filter",
    "auto_part": "Car part",
    "mower": "Mower",
    "tool": "Tool",
    "equipment": "Equipment",
    "vehicle": "Vehicle",
    "unknown": "Unknown",
}

# kind -> (item_type, attach_to, location_hint)
KIND_META = {
    "food": ("grocery", None, "pantry"),
    "drink": ("grocery", None, "fridge"),
    "household": ("grocery", None, "pantry"),
    "pet": ("grocery", None, "pantry"),
    "beauty": ("grocery", None, "bathroom"),
    "aa_battery": ("grocery", None, "junk drawer"),
    "car_battery": ("grocery", "vehicle", "garage"),
    "motor_oil": ("grocery", "vehicle", "garage"),
    "filter": ("grocery", "vehicle", "garage"),
    "auto_part": ("grocery", "vehicle", "garage"),
    "mower": ("tool", "tool", "garage"),
    "tool": ("tool", None, "garage"),
    "equipment": ("tool", None, "garage"),
    "vehicle": ("vehicle", None, "driveway"),
    "unknown": ("grocery", None, None),
}

# Specific phrases first.
_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "car_battery",
        (
            "car battery",
            "auto battery",
            "automotive battery",
            "truck battery",
            "marine battery",
            "lawn tractor battery",
            "group 24",
            "group 27",
            "group 34",
            "group 35",
            "group 48",
            "group 49",
            "group 65",
            "group 78",
            "group 94r",
            "h6 battery",
            "h7 battery",
            "h8 battery",
            "agm battery",
            "lead acid",
            "diehard",
            "optima yellow",
            "optima red",
            "optima blue",
            "everstart maxx",
            "duralast",
            "interstate battery",
            "yellow top",
            "red top",
            "starting battery",
        ),
    ),
    (
        "aa_battery",
        (
            "aaa battery",
            "aa battery",
            "aaaa",
            "9 volt",
            "9v battery",
            "c battery",
            "d battery",
            "cr2032",
            "cr2025",
            "lithium coin",
            "alkaline battery",
            "rechargeable aa",
            "rechargeable aaa",
            "duracell",
            "energizer battery",
            "rayovac",
        ),
    ),
    (
        "motor_oil",
        (
            "motor oil",
            "engine oil",
            "synthetic oil",
            "5w-20",
            "5w-30",
            "5w30",
            "0w-20",
            "0w20",
            "10w-30",
            "10w30",
            "15w-40",
            "dexos",
            "pennzoil",
            "mobil 1",
            "valvoline",
            "castrol",
        ),
    ),
    (
        "filter",
        (
            "oil filter",
            "air filter",
            "cabin filter",
            "cabin air",
            "fuel filter",
            "engine air filter",
            "wix filter",
            "fram extra guard",
            "purolator",
            "k&n",
        ),
    ),
    (
        "mower",
        (
            "lawn mower",
            "lawnmower",
            "riding mower",
            "zero turn",
            "string trimmer",
            "weed eater",
            "leaf blower",
            "chainsaw",
            "pressure washer",
            "snow blower",
            "snowblower",
        ),
    ),
    (
        "auto_part",
        (
            "alternator",
            "spark plug",
            "brake pad",
            "brake rotor",
            "wiper blade",
            "serpentine",
            "timing belt",
            "coolant",
            "antifreeze",
            "transmission fluid",
            "power steering",
            "windshield washer",
            "headlight",
            "tail light",
            "ignition coil",
            "oxygen sensor",
            "catalytic",
            "cv axle",
            "starter motor",
            "radiator",
        ),
    ),
    (
        "vehicle",
        ("passenger car", "pickup truck", "sport utility", "minivan", "motorcycle vin"),
    ),
    (
        "drink",
        (
            "soda",
            "cola",
            "soft drink",
            "beverage",
            "juice",
            "sparkling water",
            "energy drink",
            "sports drink",
            "beer",
            "wine",
            "coffee drink",
            "kombucha",
        ),
    ),
    (
        "pet",
        ("dog food", "cat food", "pet food", "cat litter", "dog treat", "cat treat"),
    ),
    (
        "beauty",
        (
            "shampoo",
            "conditioner",
            "toothpaste",
            "deodorant",
            "lotion",
            "moisturizer",
            "sunscreen",
            "body wash",
            "mouthwash",
        ),
    ),
    (
        "household",
        (
            "paper towel",
            "toilet paper",
            "laundry detergent",
            "dish soap",
            "trash bag",
            "aluminum foil",
            "plastic wrap",
            "cleaner",
            "disinfectant",
            "sponge",
        ),
    ),
    (
        "tool",
        (
            "drill",
            "impact driver",
            "circular saw",
            "angle grinder",
            "air compressor",
            "generator",
            "ladder",
            "socket set",
            "wrench",
            "hammer",
            "knife",
            "knives",
            "chef knife",
            "steak knife",
            "utility knife",
        ),
    ),
    (
        "food",
        (
            "cereal",
            "pasta",
            "bread",
            "milk",
            "cheese",
            "yogurt",
            "snack",
            "chips",
            "cookie",
            "soup",
            "sauce",
            "rice",
            "beans",
            "frozen",
            "grocery",
        ),
    ),
)

_QUESTIONS = {
    "car_battery": "Which vehicle is this battery for?",
    "motor_oil": "Which vehicle is this oil for?",
    "filter": "Which vehicle is this filter for?",
    "auto_part": "Which vehicle is this part for?",
    "mower": "Want a photo of the serial plate or the odd bolt?",
    "aa_battery": "AA/AAA for remotes, or something else?",
    "tool": "Want a photo of how it starts, or where it lives?",
}


def _blob(lookup: dict | None, extra: str = "") -> str:
    lookup = lookup or {}
    parts = [
        extra,
        lookup.get("name") or "",
        lookup.get("brand") or "",
        lookup.get("category") or "",
        lookup.get("quantity") or lookup.get("size") or "",
        lookup.get("ingredients") or "",
        " ".join(str(v) for v in (lookup.get("facts") or {}).values())
        if isinstance(lookup.get("facts"), dict)
        else "",
    ]
    return " ".join(str(p) for p in parts if p).lower()


def classify_text(text: str) -> str:
    hay = (text or "").lower()
    if not hay.strip():
        return "unknown"
    # Bare "battery" without household-cell hints is usually a car battery
    # in a garage household OS — still ask, but prefer car.
    for kind, phrases in _RULES:
        for p in phrases:
            if p in hay:
                return kind
    if "battery" in hay and not any(x in hay for x in ("aa", "aaa", "9v", "coin", "alkaline")):
        return "car_battery"
    return "unknown"


def classify_product(lookup: dict | None, extra: str = "") -> dict[str, Any]:
    lookup = lookup or {}
    source = (lookup.get("source") or "").lower()
    hay = _blob(lookup, extra)
    kind = classify_text(hay)
    if kind == "unknown" and source in ("openfoodfacts", "openpetfoodfacts"):
        if lookup.get("name"):
            kind = "pet" if source == "openpetfoodfacts" else "food"
    if kind == "unknown" and source == "openbeautyfacts" and lookup.get("name"):
        kind = "beauty"
    item_type, attach_to, location = KIND_META.get(kind, KIND_META["unknown"])
    label = KIND_LABELS.get(kind, "Unknown")
    questions = []
    q = _QUESTIONS.get(kind)
    if q:
        questions.append(q)
    if kind == "car_battery":
        message = "Looks like a car battery — which vehicle, or just the garage?"
    elif kind == "motor_oil":
        message = "Looks like motor oil — which vehicle?"
    elif kind == "filter":
        message = "Looks like a filter — which vehicle?"
    elif kind == "auto_part":
        message = "Looks like a car part — which vehicle is it for?"
    elif kind == "aa_battery":
        message = "Household battery (AA/AAA/etc), not a car battery."
    elif kind == "mower":
        message = "Looks like yard equipment. Save as a tool — photo of the serial plate helps."
    elif kind in ("food", "drink", "pet", "beauty", "household"):
        name = (lookup.get("name") or "This").strip() or "This"
        message = f"{name} isn't in the house yet. Want it?"
    elif kind == "tool":
        message = "Looks like a tool. Save it, and snap the odd bolt if you want."
    elif kind == "vehicle":
        message = "Looks like a vehicle. Add plate or VIN if you have it."
    else:
        message = "Not in the house yet. Grocery, tool, or car part?"
    confidence = 0.2 if kind == "unknown" else 0.72
    if kind != "unknown" and lookup.get("name"):
        confidence = 0.84
    return {
        "item_type": item_type,
        "kind": kind,
        "kind_label": label,
        "attach_to": attach_to,
        "location_hint": location,
        "confidence": confidence,
        "questions": questions,
        "message": message,
        "source": "heuristic",
    }


_AI_SYSTEM = """You classify a household scan for Family OS.
Reply with JSON only, no markdown:
{
  "item_type": "grocery" | "tool" | "vehicle" | "custom",
  "kind": "food|drink|household|pet|beauty|aa_battery|car_battery|motor_oil|filter|auto_part|mower|tool|equipment|vehicle|unknown",
  "kind_label": "short label",
  "name": "short household name from the catalog (Frosted Flakes, not the full title)",
  "pack_count": null,
  "attach_to": "vehicle" | "tool" | null,
  "location_hint": "one place from the house list, or fridge/pantry/garage/bathroom",
  "confidence": 0.0-1.0,
  "questions": ["one short question if a human must choose"],
  "message": "one short sentence: what it is and where you put it",
  "why": "one short sentence why that room"
}
Rules:
- Parse the UPC catalog fields you were given. name is what the family would call it.
- pack_count is how many units are in the box if the catalog says so (30 for a 30-count bag of chips). null if unknown. Never guess a count that is not in the data.
- Pick location_hint from the house's place list when you can (Fridge, Pantry, Garage…).
- A 12V / group-size / AGM / DieHard / EverStart car battery is kind=car_battery, item_type=grocery (consumable), attach_to=vehicle. Ask which vehicle. Location garage or driveway.
- AA/AAA/C/D/9V/CR2032 is aa_battery, not a car battery. Junk drawer or pantry.
- Motor oil, oil/air/cabin filters, wiper blades, coolant: grocery + attach_to=vehicle. Garage.
- Lawn mowers, trimmers, chainsaws, drills: tool. Garage.
- Food: pantry. Drinks and dairy: fridge. Frozen: freezer. Soap/shampoo: bathroom.
- If the UPC catalog called a car part 'food', override it.
- Site is a household OS, not a chatbot. Be brief.
"""


def refine_with_ai(lookup: dict | None, heuristic: dict, household=None, extra: str = "") -> dict:
    """Best-effort AI pass. Never raises; returns heuristic on miss."""
    out = dict(heuristic or {})
    if household is None:
        return out
    try:
        from app.utils.ai import complete_json, get_ai_config
    except Exception:
        return out
    cfg = get_ai_config(household, household_only=True)
    if not cfg.get("ready"):
        return out
    lookup = lookup or {}
    try:
        from app.utils.places import list_places

        rooms = ", ".join(list_places(household))
    except Exception:
        rooms = "Fridge, Freezer, Pantry, Bathroom, Junk drawer, Garage, Laundry, Hall closet, Driveway"
    prompt = (
        f"House places: {rooms}\n"
        f"Barcode: {lookup.get('barcode') or ''}\n"
        f"Name: {lookup.get('name') or ''}\n"
        f"Brand: {lookup.get('brand') or ''}\n"
        f"Category: {lookup.get('category') or ''}\n"
        f"Size: {lookup.get('quantity') or lookup.get('size') or ''}\n"
        f"Catalog: {lookup.get('source') or ''}\n"
        f"Ingredients: {(lookup.get('ingredients') or '')[:400]}\n"
        f"Extra: {extra[:400]}\n"
        f"Heuristic guess: {out.get('kind')} ({out.get('kind_label')})"
    )
    ok, data = complete_json(
        prompt,
        system=_AI_SYSTEM,
        max_tokens=280,
        timeout=8,
        household=household,
        household_only=True,
    )
    if not ok or not isinstance(data, dict):
        return out
    kind = str(data.get("kind") or out.get("kind") or "unknown").strip().lower()
    if kind not in KIND_META:
        kind = out.get("kind") or "unknown"
    item_type = str(data.get("item_type") or "").strip().lower()
    if item_type not in ("grocery", "tool", "vehicle", "custom"):
        item_type, attach_to, location = KIND_META[kind]
    else:
        attach_to = data.get("attach_to")
        if attach_to not in ("vehicle", "tool", None, ""):
            attach_to = KIND_META[kind][1]
        if attach_to == "":
            attach_to = None
        location = data.get("location_hint") or KIND_META[kind][2]
    questions = data.get("questions") if isinstance(data.get("questions"), list) else out.get("questions") or []
    questions = [str(q).strip() for q in questions if str(q).strip()][:2]
    try:
        conf = float(data.get("confidence") or out.get("confidence") or 0.5)
    except Exception:
        conf = 0.5
    conf = max(0.0, min(conf, 1.0))
    message = str(data.get("message") or out.get("message") or "").strip()
    why = str(data.get("why") or "").strip()[:240]
    label = str(data.get("kind_label") or KIND_LABELS.get(kind) or kind).strip()[:80]
    clean_name = str(data.get("name") or "").strip()
    if clean_name and len(clean_name) >= 2:
        out["name"] = clean_name[:200]
    pack = data.get("pack_count")
    try:
        pack_n = int(pack) if pack not in (None, "", False) else None
    except (TypeError, ValueError):
        pack_n = None
    if pack_n and 2 <= pack_n <= 500:
        out["pack_count"] = pack_n
    try:
        from app.utils.places import snap_location

        location = snap_location(location, household) or location
    except Exception:
        pass
    out.update(
        {
            "item_type": item_type,
            "kind": kind,
            "kind_label": label,
            "attach_to": attach_to,
            "location_hint": location,
            "confidence": conf,
            "questions": questions,
            "message": message,
            "why": why,
            "source": "ai",
        }
    )
    return out


def parse_pantry_places(household, items: list) -> dict:
    """One AI pass: put on-hand groceries into rooms. Heuristic if no key."""
    from app.utils.places import list_places, snap_location
    from app.utils.ai import complete
    from sqlalchemy.orm.attributes import flag_modified

    rooms = list_places(household)
    rows = []
    for item in items:
        g = getattr(item, "grocery", None)
        if g is None:
            continue
        rows.append(
            {
                "id": item.id,
                "name": item.name,
                "brand": g.brand or "",
                "qty": str(g.quantity or ""),
                "here": (g.default_location or "").strip(),
            }
        )
    report = {"used_ai": False, "lines": [], "moved": 0, "error": None}
    if not rows:
        report["error"] = "Nothing to place."
        return report
    placements = {}
    ok, text = complete(
        "Items:\n"
        + "\n".join(
            f"- id={r['id']} name={r['name']} brand={r['brand']} qty={r['qty']} current={r['here'] or '(none)'}"
            for r in rows[:80]
        ),
        system=(
            "You put household groceries into rooms. JSON only:\n"
            '{"placements":[{"id":1,"location":"Fridge","why":"dairy"}]}\n'
            f"Rooms you may use: {', '.join(rooms)}.\n"
            "Keep current location if it already looks right. Empty location if you are unsure."
        ),
        max_tokens=1200,
        timeout=45,
        household=household,
        household_only=True,
    )
    if ok and text:
        report["used_ai"] = True
        try:
            import json
            raw = text.strip()
            if "```" in raw:
                raw = raw.split("```", 2)[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw)
            for p in data.get("placements") or []:
                try:
                    iid = int(p.get("id"))
                except Exception:
                    continue
                loc = snap_location(p.get("location"), household)
                if loc:
                    placements[iid] = {"location": loc, "why": (p.get("why") or "")[:160]}
        except Exception as exc:
            report["error"] = f"AI answered but was not JSON ({exc}). Used guesses."
    if not placements:
        for r in rows:
            if r["here"]:
                continue
            guess = classify({"name": r["name"], "brand": r["brand"]}, household=household, extra=r["name"], use_ai=False)
            loc = snap_location(guess.get("location_hint"), household)
            if loc:
                placements[r["id"]] = {"location": loc, "why": guess.get("message") or "guess"}
    by_room: dict[str, list[str]] = {}
    for item in items:
        g = getattr(item, "grocery", None)
        hit = placements.get(item.id)
        if not hit or g is None:
            continue
        if (g.default_location or "").strip() == hit["location"]:
            continue
        g.default_location = hit["location"]
        extra = dict(g.extra_data or {})
        extra["ai"] = {
            "used_ai": report["used_ai"],
            "location": hit["location"],
            "why": hit["why"],
            "kind": "pantry parse",
        }
        g.extra_data = extra
        flag_modified(g, "extra_data")
        report["moved"] += 1
        by_room.setdefault(hit["location"], []).append(item.name)
    report["lines"] = [f"{room}: {', '.join(names)}" for room, names in sorted(by_room.items())]
    return report


def place_new_grocery(item, g, lookup, household) -> dict:
    """Set default_location from AI if a key exists, else heuristic. Never raises."""
    report = {
        "used_ai": False,
        "kind": "",
        "location": None,
        "confidence": None,
        "why": "",
        "questions": [],
    }
    try:
        from sqlalchemy.orm.attributes import flag_modified
        from app.utils.places import snap_location

        guess = classify(lookup, household=household, extra=getattr(item, "name", "") or "", use_ai=True)
        loc = snap_location(guess.get("location_hint"), household)
        if loc and not (g.default_location or "").strip():
            g.default_location = loc
        try:
            from app.utils.barcode_lookup import is_placeholder_name
        except Exception:
            is_placeholder_name = lambda n: not (n or "").strip()
        if guess.get("name") and is_placeholder_name(getattr(item, "name", None)):
            item.name = str(guess["name"])[:200]
        report = {
            "used_ai": guess.get("source") == "ai",
            "kind": guess.get("kind_label") or guess.get("kind") or "",
            "location": loc or guess.get("location_hint"),
            "confidence": guess.get("confidence"),
            "why": guess.get("why") or guess.get("message") or "",
            "questions": guess.get("questions") or [],
        }
        extra = g.extra_data if isinstance(g.extra_data, dict) else {}
        extra = dict(extra)
        extra["ai"] = report
        pack = guess.get("pack_count")
        if pack:
            usual = dict(extra.get("usual") or {})
            if not usual.get("into"):
                usual["into"] = int(pack)
                usual["into_hist"] = [int(pack)]
                extra["usual"] = usual
        g.extra_data = extra
        flag_modified(g, "extra_data")
    except Exception:
        pass
    return report


def classify(lookup: dict | None, household=None, extra: str = "", use_ai: bool = True) -> dict:
    heuristic = classify_product(lookup, extra=extra)
    if use_ai and household is not None:
        return refine_with_ai(lookup, heuristic, household=household, extra=extra)
    return heuristic


def household_anchors(household_id: int) -> dict:
    from app.builddb.table_items import Item

    vehicles = (
        Item.query.filter_by(household_id=household_id, item_type="vehicle")
        .order_by(Item.name.asc())
        .all()
    )
    tools = (
        Item.query.filter_by(household_id=household_id, item_type="tool")
        .order_by(Item.name.asc())
        .all()
    )
    return {
        "vehicles": [{"id": v.id, "name": v.name} for v in vehicles],
        "tools": [{"id": t.id, "name": t.name} for t in tools],
    }
