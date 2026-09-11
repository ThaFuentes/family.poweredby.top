"""Split a Discord dump / wall of notes and say where each bit belongs.

Household BYOK only. No key → keyword routing still works. You confirm before save.
"""
from __future__ import annotations

import re
from datetime import datetime

DESTS = (
    "note",
    "basket",
    "reminder",
    "legal",
    "vehicle_part",
    "house_part",
    "skip",
)

DEST_LABELS = {
    "note": "Notes",
    "basket": "Basket",
    "reminder": "Due",
    "legal": "Records",
    "vehicle_part": "Vehicle",
    "house_part": "House",
    "skip": "Skip",
}

_LEGAL = (
    "citation",
    "ticket",
    "parking ticket",
    "notice",
    "court",
    "fine",
    "tow slip",
    "red tag",
    "hoa",
    "code enforcement",
    "summons",
    "warrant",
)
_BASKET = (
    "buy ",
    "we need",
    "need milk",
    "grocery",
    "groceries",
    "shopping list",
    "paper towels",
    "from the store",
    "add to the list",
    "out of ",
)
_REMIND = (
    "remind",
    "due ",
    "appointment",
    "oil change",
    "don't forget",
    "dont forget",
    "calendar",
    "next week",
    "tomorrow",
)
_VEHICLE = (
    "replaced the battery",
    "alternator",
    "radiator",
    "oil filter",
    "spark plug",
    "brake pad",
    "on the truck",
    "on the civic",
    "on the honda",
    "autozone",
    "o'reilly",
    "oreilly",
    "rockauto",
)
_HOUSE = (
    "hvac",
    "furnace",
    "water heater",
    "smoke detector",
    "co detector",
    "whole house filter",
    "sump",
)

_DISCORD_HEAD = re.compile(
    r"(?m)^(.{1,64}?\s+[—\-–]\s+\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?(?:,?\s+\d{1,2}:\d{2}(?:\s*[APap][Mm])?)?)\s*$"
)
_BULLET = re.compile(r"(?m)^\s*(?:[-*]|\d+[.)])\s+")
_DATE = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)\b"
)

_SYSTEM = """You sort household notes. Family OS is a private house file, not a chatbot.
Return ONLY JSON: {"items":[...]} with at most 40 items.
Each item:
dest: note | basket | reminder | legal | vehicle_part | house_part | skip
title: short name
body: the useful text
why: one short reason
due_on: YYYY-MM-DD or ""
kind: citation|notice|warning|ticket|court|letter|other (legal only)
agency, amount, source: strings or ""
vehicle_hint: which car if dest is vehicle_part
system, slot: vehicle/house system ids if you know them (electrical/battery, cooling/radiator, hvac/filter…)
visibility: household | personal
Split Discord dumps (Name — date) into one item per message that matters.
Skip hellos, memes, and empty reactions.
Grocery/shopping → basket. Tickets/notices/fines → legal.
Replaced a car part → vehicle_part. HVAC/water heater/smoke → house_part.
A date to do something → reminder. Everything else useful → note.
"""


def dest_of(raw: str) -> str:
    d = (raw or "").strip().lower().replace("-", "_")
    aliases = {
        "notes": "note",
        "grocery": "basket",
        "groceries": "basket",
        "list": "basket",
        "shopping": "basket",
        "due": "reminder",
        "calendar": "reminder",
        "records": "legal",
        "citation": "legal",
        "ticket": "legal",
        "vehicle": "vehicle_part",
        "car": "vehicle_part",
        "part": "vehicle_part",
        "house": "house_part",
        "ignore": "skip",
        "trash": "skip",
    }
    d = aliases.get(d, d)
    return d if d in DESTS else "note"


def split_dump(raw: str) -> list[str]:
    text = (raw or "").replace("\r\n", "\n").strip()
    if not text:
        return []
    if _DISCORD_HEAD.search(text):
        chunks = []
        matches = list(_DISCORD_HEAD.finditer(text))
        for i, m in enumerate(matches):
            if i == 0 and m.start() > 0:
                head = text[: m.start()].strip()
                if head:
                    chunks.append(head)
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            bit = text[m.start() : end].strip()
            if bit:
                chunks.append(bit)
        out = [_clean_chunk(c) for c in chunks if _clean_chunk(c)]
        if out:
            return out[:40]
    lines = [ln.rstrip() for ln in text.split("\n")]
    bullets = [ln for ln in lines if _BULLET.match(ln)]
    if len(bullets) >= 3 and len(bullets) >= max(3, len(lines) // 3):
        return [_BULLET.sub("", ln).strip() for ln in bullets if _BULLET.sub("", ln).strip()][:40]
    parts = [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]
    if len(parts) >= 2:
        return [_clean_chunk(p) for p in parts if _clean_chunk(p)][:40]
    return [text[:4000]]


def _clean_chunk(raw: str) -> str:
    s = (raw or "").strip()
    s = _DISCORD_HEAD.sub("", s, count=1).strip()
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s[:4000]


def _has_any(text: str, needles: tuple[str, ...]) -> bool:
    t = f" {text.lower()} "
    return any(n in t for n in needles)


def guess_dest(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return "skip"
    low = t.lower()
    if _has_any(low, _LEGAL):
        return "legal"
    if _has_any(low, _VEHICLE):
        return "vehicle_part"
    if _has_any(low, _HOUSE):
        return "house_part"
    if _has_any(low, _REMIND):
        return "reminder"
    if _has_any(low, _BASKET):
        return "basket"
    if len(t) < 4:
        return "skip"
    return "note"


def _title_of(text: str) -> str:
    line = (text or "").strip().split("\n", 1)[0].strip()
    line = _BULLET.sub("", line).strip()
    if len(line) > 80:
        line = line[:77] + "…"
    return line or "Note"


def _due_of(text: str) -> str:
    m = _DATE.search(text or "")
    if not m:
        return ""
    raw = m.group(1)
    if re.match(r"\d{4}-\d{2}-\d{2}$", raw):
        return raw
    bits = re.split(r"[/-]", raw)
    if len(bits) == 2:
        bits.append("2026")
    if len(bits) != 3:
        return ""
    a, b, c = bits
    try:
        if len(c) == 2:
            c = "20" + c
        month, day, year = int(a), int(b), int(c)
        if month > 12 and day <= 12:
            month, day = day, month
        return f"{year:04d}-{month:02d}-{day:02d}"
    except Exception:
        return ""


def heuristic_items(raw: str) -> list[dict]:
    items = []
    for chunk in split_dump(raw):
        dest = guess_dest(chunk)
        if dest == "skip":
            continue
        items.append(
            normalize_item(
                {
                    "dest": dest,
                    "title": _title_of(chunk),
                    "body": chunk,
                    "why": "Matched words in the dump.",
                    "due_on": _due_of(chunk) if dest in ("reminder", "legal") else "",
                }
            )
        )
    return items[:40]


def normalize_item(raw: dict | None) -> dict:
    row = raw if isinstance(raw, dict) else {}
    dest = dest_of(row.get("dest") or "note")
    title = str(row.get("title") or "").strip()[:200]
    body = str(row.get("body") or "").strip()[:4000]
    if not title:
        title = _title_of(body) if body else "Note"
    vis = (str(row.get("visibility") or "household").strip().lower())
    if vis not in ("household", "personal"):
        vis = "household"
    kind = str(row.get("kind") or "").strip().lower()
    if dest == "legal" and kind not in (
        "citation",
        "notice",
        "warning",
        "ticket",
        "court",
        "letter",
        "other",
    ):
        kind = "citation"
    return {
        "dest": dest,
        "title": title,
        "body": body,
        "why": str(row.get("why") or "").strip()[:200],
        "due_on": str(row.get("due_on") or "").strip()[:10],
        "kind": kind,
        "agency": str(row.get("agency") or "").strip()[:200],
        "amount": str(row.get("amount") or "").strip()[:20],
        "source": str(row.get("source") or "").strip()[:200],
        "vehicle_hint": str(row.get("vehicle_hint") or "").strip()[:80],
        "system": str(row.get("system") or "").strip()[:40],
        "slot": str(row.get("slot") or "").strip()[:40],
        "visibility": vis,
    }


def household_context(household, vehicles=None, house_name: str | None = None) -> str:
    names = []
    for v in vehicles or []:
        extra = []
        row = getattr(v, "vehicle", None)
        if row is not None:
            extra = [str(x) for x in (row.year, row.make, row.model, row.plate) if x]
        names.append(f"{v.name}" + (f" ({' '.join(extra)})" if extra else ""))
    today = datetime.utcnow().date().isoformat()
    lines = [f"Today: {today}"]
    if names:
        lines.append("Vehicles: " + "; ".join(names[:12]))
    if house_name:
        lines.append(f"House: {house_name}")
    return "\n".join(lines)


def parse_dump(raw: str, *, household=None, vehicles=None, house_name: str | None = None) -> dict:
    """AI first when the household has a key, else keywords. Always returns items."""
    text = (raw or "").strip()
    fallback = heuristic_items(text)
    used = "words"
    if not text:
        return {"ok": True, "used": used, "items": [], "error": ""}
    if household is None:
        return {"ok": True, "used": used, "items": fallback, "error": ""}
    try:
        from app.utils.ai import complete, get_ai_config, parse_json_object
    except Exception:
        return {"ok": True, "used": used, "items": fallback, "error": ""}
    cfg = get_ai_config(household, household_only=True)
    if not cfg.get("has_key"):
        return {
            "ok": True,
            "used": used,
            "items": fallback,
            "error": "No household AI key — sorted by words. Paste a free Gemini key on Household for better splits.",
        }
    prompt = (
        household_context(household, vehicles=vehicles, house_name=house_name)
        + "\n\nDUMP:\n"
        + text[:12000]
    )
    ok, text_out = complete(
        prompt,
        system=_SYSTEM,
        max_tokens=2200,
        timeout=45,
        household=household,
        household_only=True,
    )
    if not ok:
        return {
            "ok": True,
            "used": used,
            "items": fallback,
            "error": str(text_out)[:240] or "AI did not answer. Used word matching.",
        }
    data = parse_json_object(text_out)
    items_raw = None
    if isinstance(data, dict):
        if isinstance(data.get("items"), list):
            items_raw = data["items"]
        elif data.get("dest") or data.get("title"):
            items_raw = [data]
    if items_raw is None:
        arr = _parse_array(text_out)
        if arr:
            items_raw = arr
    if not items_raw:
        return {
            "ok": True,
            "used": used,
            "items": fallback,
            "error": "AI did not return a list. Used word matching.",
        }
    items = []
    for row in items_raw[:40]:
        if isinstance(row, str):
            row = {"title": row, "body": row, "dest": guess_dest(row)}
        if not isinstance(row, dict):
            continue
        items.append(normalize_item(row))
    if not items:
        return {"ok": True, "used": used, "items": fallback, "error": "AI list was empty."}
    return {"ok": True, "used": "ai", "items": items, "error": ""}


def _parse_array(text: str):
    import json

    raw = (text or "").strip()
    start = raw.find("[")
    end = raw.rfind("]")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
    except Exception:
        return None
    return data if isinstance(data, list) else None


def match_vehicle(vehicles, hint: str):
    needle = (hint or "").strip().lower()
    rows = list(vehicles or [])
    if not rows:
        return None
    if not needle:
        return rows[0] if len(rows) == 1 else None
    for it in rows:
        blob = (it.name or "").lower()
        v = getattr(it, "vehicle", None)
        if v is not None:
            blob += " " + " ".join(
                str(x or "").lower() for x in (v.make, v.model, v.plate, v.year)
            )
        if needle in blob:
            return it
    return rows[0] if len(rows) == 1 else None


def apply_item(hid: int, user, item: dict, *, vehicles=None, house=None) -> tuple[bool, str]:
    """Write one confirmed card. Returns (ok, where)."""
    from app.builddb.builddb import db
    from app.builddb.table_grocery_list import GroceryListEntry
    from app.builddb.table_legal_records import LegalRecord
    from app.builddb.table_notes import Note
    from app.builddb.table_reminders import Reminder
    from app.utils.permissions import can
    from app.utils.vehicle_systems import guess_slot, install_part, valid_slot, valid_system

    row = normalize_item(item)
    dest = row["dest"]
    if dest == "skip":
        return True, "skip"
    title = row["title"]
    body = row["body"]
    uid = getattr(user, "id", None)

    if dest == "legal":
        if not can("legal", user):
            dest = "note"
        else:
            rec = LegalRecord(
                household_id=hid,
                created_by=uid,
                kind=row["kind"] or "citation",
                status="open",
                title=title,
                agency=row["agency"] or None,
                body=body or None,
                issued_on=_parse_day(row["due_on"]),
            )
            if row["amount"]:
                from app.utils.vehicle_systems import parse_cost

                rec.amount = parse_cost(row["amount"])
            db.session.add(rec)
            return True, "Records"

    if dest == "basket":
        if not (can("edit_grocery", user) or can("scan", user)):
            dest = "note"
        else:
            db.session.add(
                GroceryListEntry(
                    household_id=hid,
                    name=title[:200],
                    status="open",
                    added_reason="sort",
                    created_by=uid,
                )
            )
            return True, "Basket"

    if dest == "reminder":
        if not can("maintain", user):
            dest = "note"
        else:
            due = None
            if row["due_on"]:
                try:
                    due = datetime.fromisoformat(row["due_on"])
                except Exception:
                    due = None
            db.session.add(
                Reminder(
                    household_id=hid,
                    title=title[:200],
                    type="custom",
                    due_at=due,
                    notes=body or None,
                    status="open",
                    created_by=uid,
                )
            )
            return True, "Due"

    if dest == "vehicle_part":
        if not can("maintain", user):
            dest = "note"
        else:
            vehicle = match_vehicle(vehicles, row["vehicle_hint"])
            if vehicle is None:
                dest = "note"
            else:
                system, slot = guess_slot(None, name=title + " " + body)
                if row["system"]:
                    system = valid_system(row["system"])
                if row["slot"]:
                    slot = valid_slot(system, row["slot"])
                install_part(
                    hid=hid,
                    vehicle_item_id=vehicle.id,
                    user_id=uid,
                    system=system,
                    slot=slot,
                    name=title[:200],
                    source=row["source"] or None,
                    notes=body or None,
                    status="installed",
                )
                return True, f"Vehicle · {vehicle.name}"

    if dest == "house_part":
        if not can("maintain", user) or house is None:
            dest = "note"
        else:
            from app.utils.house_systems import HOUSE_SLOTS, install_house_part

            system = valid_system(row["system"] or "other", HOUSE_SLOTS)
            slot = valid_slot(system, row["slot"] or "misc", HOUSE_SLOTS)
            install_house_part(
                hid=hid,
                vehicle_item_id=house.id,
                user_id=uid,
                system=system,
                slot=slot,
                name=title[:200],
                source=row["source"] or None,
                notes=body or None,
                status="installed",
            )
            return True, "House"

    vis = row["visibility"] if row["visibility"] in ("household", "personal") else "household"
    db.session.add(
        Note(
            household_id=hid,
            user_id=uid,
            visibility=vis,
            title=title[:500],
            body=body or None,
        )
    )
    return True, "Notes"


def _parse_day(raw: str):
    s = (raw or "").strip()[:10]
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None
