"""Household Ask: talk to the household AI and let it look up or do work.

Uses the household BYOK key only. Kids never see it. Vault reads and writes
need the vault unlocked for this login.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime

from flask import has_request_context, session, url_for
from flask_login import current_user

from app.builddb.builddb import db
from app.utils.ai import complete, parse_json_object
from app.utils.household_ai import ask_available
from app.utils.permissions import can, role_of

SESSION_HISTORY = "family_ask_history"
SESSION_HITS = "family_ask_hits"
MAX_HISTORY = 12
MAX_TOOL_ROUNDS = 5
MAX_HITS = 24
HIT_WINDOW = 600
MSG_CAP = 2000

TOOLS = (
    "find",
    "house",
    "due",
    "lookup",
    "vault_unlock",
    "vault_list",
    "vault_open",
    "vault_save",
    "note_save",
    "basket_add",
    "basket_match",
    "reminder_save",
    "inventory",
    "tool_save",
    "vehicle_save",
    "place",
    "guide",
    "member_add",
    "member_list",
    "member_role",
    "part_save",
    "log_save",
    "legal_save",
    "oil_save",
)

WRITE_TOOLS = (
    "vault_save",
    "note_save",
    "basket_add",
    "basket_match",
    "reminder_save",
    "inventory",
    "tool_save",
    "vehicle_save",
    "vault_unlock",
    "place",
    "member_add",
    "member_role",
    "part_save",
    "log_save",
    "legal_save",
    "oil_save",
)

SYSTEM = """You are Ask in Family OS. Do the house work this person is already allowed to do: people, vault, bills, tools, parts, vehicles, the house, notes, inventory, basket, logs, legal paper, and photos.

Reply with ONLY JSON. To act:
{"tool":"find","args":{"q":"batteries"}}
{"tool":"house","args":{"kind":"tools"}}
{"tool":"house","args":{"kind":"vehicles"}}
{"tool":"house","args":{"kind":"basket"}}
{"tool":"due","args":{}}
{"tool":"lookup","args":{"upc":"012345678905"}}
{"tool":"lookup","args":{"vin":"1HGCM82633A004352"}}
{"tool":"lookup","args":{"plate":"ABC1234"}}
{"tool":"vault_unlock","args":{"password":"their Family OS password","username":""}}
{"tool":"vault_list","args":{"q":"netflix"}}
{"tool":"vault_open","args":{"id":12}}
{"tool":"vault_save","args":{"kind":"password","title":"Netflix","login":"a","secret":"x","url":"https://netflix.com","phone":"","account_no":"","two_factor":"app","call_info":"","details":"","share":"personal"}}
{"tool":"vault_save","args":{"kind":"billing","title":"City water","account_no":"W-1","phone":"555","url":"","login":"","secret":"","share":"personal"}}
{"tool":"note_save","args":{"title":"Grill cover","body":"…","share":"household","id":null}}
{"tool":"basket_add","args":{"names":["coffee creamer","paper towels"],"store":"Sam's"}}
{"tool":"basket_match","args":{"item_id":55,"entry_id":12}}
{"tool":"basket_match","args":{"q":"french vanilla creamer"}}
{"tool":"reminder_save","args":{"title":"City water","type":"bill","due":"2026-10-01","every":"30d"}}
{"tool":"inventory","args":{"q":"milk","action":"restock","amount":1,"place":"fridge"}}
{"tool":"inventory","args":{"q":"Frosted Flakes","action":"create","upc":"016000275273","amount":1,"place":"pantry"}}
{"tool":"tool_save","args":{"name":"DeWalt drill","type":"drill","model":"DCD771","serial":"","barcode":"","notes":""}}
{"tool":"vehicle_save","args":{"vin":"","plate":"","name":"","make":"","model":"","year":""}}
{"tool":"place","args":{"what":"tool","name":"DeWalt 20V drill","brand":"DeWalt","model":"DCD771","serial":"","barcode":"","part_number":"","vehicle":"","notes":""}}
{"tool":"part_save","args":{"name":"front brake pads","vehicle":"Silverado","brand":"","model":"","serial":"","part_number":"","spec":""}}
{"tool":"member_list","args":{}}
{"tool":"member_add","args":{"name":"Sam","username":"sam","role":"member","email":"","password":""}}
{"tool":"member_role","args":{"username":"sam","role":"member"}}
{"tool":"log_save","args":{"item":"Silverado","kind":"miles","reading":"81200","notes":""}}
{"tool":"oil_save","args":{"item":"Silverado","needs":"5W-30 full synthetic API SP","capacity":"6 qt","in_it":"Mobil 1 5W-30","last_date":"2026-03-01","last_miles":"80000","interval_miles":"5000","interval_months":"6"}}
{"tool":"note_save","args":{"title":"Spare key","body":"In the kitchen drawer.","item":"Silverado","share":"household"}}
{"tool":"legal_save","args":{"title":"Parking ticket","kind":"ticket","agency":"","due":"","amount":"","body":""}}
{"tool":"guide","args":{"action":"add_person"}}

place what: tool, part, grocery, vehicle, house, note, legal.
A photo with a barcode, VIN, or serial: read the code, then place or lookup. No code: identify the tool or part and place it. Do not invent codes.
Oil: needs is the exact text for the Oil it needs field. in_it is what was poured. capacity, last_date, last_miles, interval_miles, and interval_months fill those form fields. Do not say the oil was added unless oil_save returns a needs value. Notes with item are pinned on that vehicle, tool, or equipment.
If they say add that, save that, or put that on a vehicle, tool, or the house, save your previous reply on that item with note_save. When the reply is an oil spec, also oil_save with needs set to that spec. Do not ask them to paste it again.
Adding a person: call member_add only when you have a name and username. If either is missing, ask. Role member, admin, or child. Password may be blank.
When member_add returns a password, say the username and password once so they can copy it.
inventory action: restock, used, set, need, create.
vault kind: password, billing, info. share: personal or household.
two_factor: none, sms, app, email, hardware, other.
reminder type: bill, oil_change, filter, custom. every: 30d, 90d, 180d, 365d, 3000mi, 5000mi, 50h, or monthly/yearly.
To talk: {"say":"short answer with /vault/12 /items/4 /find/?q=oil or https links."}

If they name a store run (Sam's, Costco) put those names on the basket with store set — no barcode yet. When they later scan a product that fits (french vanilla creamer vs coffee creamer), call basket_match so it links and comes off the list.
If vault is locked, call vault_unlock when they gave the password, else tell them to open /vault/ or paste the password.
Look up a UPC/VIN before creating a tool, vehicle, or grocery when they gave a code.
Do not invent counts, passwords, VINs, or bills. Keep answers short.
"""


def _utcnow():
    return datetime.utcnow()


def ask_ready(household=None, user=None) -> bool:
    u = user if user is not None else current_user
    h = household
    if h is None:
        h = getattr(u, "household", None)
    if not getattr(u, "is_authenticated", False):
        return False
    if role_of(u) == "child":
        return False
    return ask_available(h, u)


def _trim(value, cap: int) -> str:
    return ("" if value is None else str(value)).strip()[:cap]


def _history() -> list:
    if not has_request_context():
        return []
    stored = _load_turns()
    if stored:
        return stored
    rows = session.get(SESSION_HISTORY) or []
    if not isinstance(rows, list):
        return []
    return rows[-MAX_HISTORY:]


def _save_history(rows: list) -> None:
    if not has_request_context():
        return
    session[SESSION_HISTORY] = rows[-MAX_HISTORY:]
    _store_latest(rows)


TURN_KEEP = 40


def _turn_user():
    if not has_request_context() or not getattr(current_user, "is_authenticated", False):
        return None
    uid = int(getattr(current_user, "id", 0) or 0)
    hid = int(getattr(current_user, "household_id", 0) or 0)
    if not uid or not hid:
        return None
    return uid, hid


def _load_turns() -> list:
    who = _turn_user()
    if not who:
        return []
    try:
        from app.builddb.table_ask_turns import AskTurn

        uid, hid = who
        rows = (
            AskTurn.query.filter_by(household_id=hid, user_id=uid)
            .order_by(AskTurn.id.desc())
            .limit(16)
            .all()
        )
    except Exception:
        return []
    out = []
    for row in reversed(rows):
        text = (row.body or "").strip()
        if text and row.role in ("user", "assistant"):
            out.append({"role": row.role, "text": text[:4000]})
    return out


def _store_latest(rows: list) -> None:
    who = _turn_user()
    if not who or not rows:
        return
    last_user = ""
    last_assistant = ""
    for row in rows:
        if row.get("role") == "user":
            last_user = (row.get("text") or "").strip()
        elif row.get("role") == "assistant":
            last_assistant = (row.get("text") or "").strip()
    if not last_assistant:
        return
    try:
        from app.builddb.table_ask_turns import AskTurn

        uid, hid = who
        latest = (
            AskTurn.query.filter_by(household_id=hid, user_id=uid, role="assistant")
            .order_by(AskTurn.id.desc())
            .first()
        )
        if latest is not None and (latest.body or "").strip() == last_assistant:
            return
        if last_user:
            db.session.add(AskTurn(household_id=hid, user_id=uid, role="user", body=last_user[:4000]))
        db.session.add(AskTurn(household_id=hid, user_id=uid, role="assistant", body=last_assistant[:4000]))
        db.session.flush()
        stale = (
            AskTurn.query.filter_by(household_id=hid, user_id=uid)
            .order_by(AskTurn.id.desc())
            .offset(TURN_KEEP)
            .all()
        )
        for row in stale:
            db.session.delete(row)
        db.session.commit()
    except Exception:
        db.session.rollback()


def _clear_turns() -> None:
    who = _turn_user()
    if not who:
        return
    try:
        from app.builddb.table_ask_turns import AskTurn

        uid, hid = who
        AskTurn.query.filter_by(household_id=hid, user_id=uid).delete(synchronize_session=False)
        db.session.commit()
    except Exception:
        db.session.rollback()


def clear_history() -> None:
    if has_request_context():
        session.pop(SESSION_HISTORY, None)
        _clear_turns()
    try:
        from app.utils.ask_photo import clear_ask_photo

        clear_ask_photo()
    except Exception:
        pass


def _rate_ok() -> bool:
    if not has_request_context():
        return True
    now = int(time.time())
    hits = [int(t) for t in (session.get(SESSION_HITS) or []) if isinstance(t, (int, float, str))]
    hits = [t for t in hits if now - int(t) < HIT_WINDOW]
    if len(hits) >= MAX_HITS:
        session[SESSION_HITS] = hits
        return False
    hits.append(now)
    session[SESSION_HITS] = hits
    return True


def _path(endpoint, **kwargs) -> str:
    try:
        return url_for(endpoint, **kwargs)
    except Exception:
        return ""


def _find_items(q: str, item_type: str | None = None, limit: int = 8):
    from app.builddb.table_items import Item
    from app.utils.household import household_id

    needle = _trim(q, 80)
    qry = Item.query.filter_by(household_id=household_id()).filter(Item.removed_at.is_(None))
    if item_type:
        qry = qry.filter_by(item_type=item_type)
    if needle.isdigit():
        row = qry.filter_by(id=int(needle)).first()
        return [row] if row else []
    if len(needle) >= 2:
        like = f"%{needle}%"
        qry = qry.filter(Item.name.ilike(like))
    elif needle:
        return []
    return qry.order_by(Item.name.asc()).limit(limit).all()


def tool_house(args: dict | None = None) -> dict:
    args = args if isinstance(args, dict) else {}
    kind = _trim(args.get("kind") or args.get("what") or "tools", 20).lower()
    if kind in ("tool", "tools", "drill", "drills"):
        rows = _find_items("", "tool", limit=40)
        lines = [_item_line(i) for i in rows]
        return {
            "ok": True,
            "kind": "tools",
            "count": len(lines),
            "lines": lines,
            "href": "/tools/",
            "empty": "No tools saved yet. Add one on /tools/ or tell me the name.",
        }
    if kind in ("vehicle", "vehicles", "car", "cars", "truck", "trucks"):
        rows = _find_items("", "vehicle", limit=40)
        lines = [_item_line(i) for i in rows]
        return {
            "ok": True,
            "kind": "vehicles",
            "count": len(lines),
            "lines": lines,
            "href": "/vehicles/",
            "empty": "No vehicles saved yet. Add one on /vehicles/.",
        }
    if kind in ("basket", "list", "shopping"):
        from app.builddb.table_grocery_list import GroceryListEntry
        from app.utils.household import scoped

        rows = scoped(GroceryListEntry).filter_by(status="open").order_by(GroceryListEntry.id.desc()).limit(40).all()
        lines = []
        for r in rows:
            bit = r.name
            if r.note:
                bit += f" · {r.note}"
            lines.append(bit)
        return {
            "ok": True,
            "kind": "basket",
            "count": len(lines),
            "lines": lines,
            "href": "/groceries/list",
            "empty": "Basket is empty.",
        }
    if kind in ("grocery", "groceries", "inventory", "pantry", "food"):
        rows = _find_items("", "grocery", limit=40)
        lines = [_item_line(i) for i in rows]
        return {
            "ok": True,
            "kind": "inventory",
            "count": len(lines),
            "lines": lines,
            "href": "/groceries/",
            "empty": "Nothing in inventory yet.",
        }
    return tool_due()


def _speak_house(result: dict) -> str:
    lines = result.get("lines") or []
    kind = result.get("kind") or "items"
    href = result.get("href") or ""
    if not lines:
        return result.get("empty") or f"No {kind} saved yet."
    body = "\n".join(f"· {ln}" for ln in lines)
    tail = f"\n{href}" if href else ""
    return f"{kind.capitalize()} in this house ({result.get('count') or len(lines)}):\n{body}{tail}"


_SAVE_THAT = re.compile(
    r"^\s*(?:please\s+)?(?:add|save|put|keep|store|pin)\s+(?:that|this|it)\s+(?:on|to|onto|in|into)\s+(?:my|the|our|this)?\s*(.+?)\s*[.!?]*\s*$",
    re.I,
)
_OIL_SPEC = re.compile(r"\b(\d{1,2}\s*W-\s*\d{2}|SAE\s*\d{2})\b", re.I)


def _last_assistant(history: list) -> str:
    for row in reversed(history or []):
        if row.get("role") == "assistant" and (row.get("text") or "").strip():
            return str(row.get("text")).strip()
    return ""


def _oil_blurb(text: str) -> str:
    match = _OIL_SPEC.search(text or "")
    if not match:
        return ""
    start = max(0, match.start() - 60)
    end = min(len(text), match.end() + 80)
    return " ".join(text[start:end].split())[:200]


def _remember_target(name: str):
    """Return an item, a dict error, or None when the name is empty."""
    label = _trim(name, 200)
    generic = {
        "vehicle": "vehicle",
        "car": "vehicle",
        "truck": "vehicle",
        "van": "vehicle",
        "suv": "vehicle",
        "tool": "tool",
        "equipment": "tool",
        "mower": "tool",
        "house": "house",
        "home": "house",
    }
    kind = generic.get(label.lower())
    if kind:
        rows = _find_items("", kind, limit=8)
    else:
        rows = []
        for item_type in ("vehicle", "tool", "house"):
            for row in _find_items(label, item_type, limit=4):
                if all(row.id != old.id for old in rows):
                    rows.append(row)
    if len(rows) == 1:
        return rows[0]
    if len(rows) > 1:
        names = ", ".join(r.name for r in rows[:6])
        return {
            "ok": True,
            "say": f"Which one? {names}",
            "did": [],
            "vault_locked": False,
        }
    return {
        "ok": True,
        "say": f"I don’t see a vehicle, tool, or equipment named {label}.",
        "did": [],
        "vault_locked": False,
    }


def _remember_reply(text: str) -> dict | None:
    """Save the previous Ask reply onto an item. No new model call."""
    match = _SAVE_THAT.match(text or "")
    if not match:
        return None
    prior = _last_assistant(_history())
    if not prior:
        return {
            "ok": True,
            "say": "Ask something first. Then say add that to the vehicle, tool, or equipment.",
            "did": [],
            "vault_locked": False,
        }
    target = _remember_target(match.group(1))
    if isinstance(target, dict):
        return target
    from app.builddb.table_notes import Note
    from app.utils.household import household_id
    from app.utils.oil import save_item_oil

    hid = household_id()
    from app.utils.oil import normalize_oil_payload, oil_payload_has_fields

    asked = ""
    for row in reversed(_history() or []):
        if row.get("role") == "user" and (row.get("text") or "").strip() and row.get("text") != text:
            asked = str(row.get("text"))
            break
    oil_data = {}
    if re.search(r"\boil\b", f"{asked}\n{prior}", re.I):
        oil_data = normalize_oil_payload({"text": prior})
    title = "Oil it needs" if oil_payload_has_fields(oil_data) else "From Ask"
    note = Note(
        household_id=hid,
        user_id=current_user.id,
        visibility="household",
        title=title,
        body=prior[:8000],
        item_id=target.id,
    )
    db.session.add(note)
    oil_saved = False
    if oil_payload_has_fields(oil_data) and (target.vehicle is not None or target.tool is not None):
        if can("maintain") or can("edit_meta"):
            save_item_oil(target, oil_data, clear=False)
            oil_saved = True
    db.session.commit()
    where = f"/items/{target.id}?tab=notes"
    extra = " The oil it needs is on that page too." if oil_saved else ""
    return {
        "ok": True,
        "say": f"Saved on {target.name}. {where}{extra}",
        "did": ["note"],
        "vault_locked": False,
    }


def _local_house_say(text: str) -> str | None:
    t = (text or "").strip().lower()
    if not t:
        return None
    if re.search(r"\b(add|save|create|new|delete|remove|share|oil|note|spec|filter|tire|battery)\b", t):
        return None
    wants = bool(re.search(r"\b(what|which|list|have|has|show|my|our|got|lookup|look up|tell)\b", t)) or t in (
        "tools",
        "vehicles",
        "basket",
        "inventory",
    )
    if not wants:
        return None
    if re.search(r"\btools?\b", t):
        return _speak_house(tool_house({"kind": "tools"}))
    if re.search(r"\b(vehicles?|cars?|trucks?)\b", t):
        return _speak_house(tool_house({"kind": "vehicles"}))
    if re.search(r"\b(basket|shopping list)\b", t):
        return _speak_house(tool_house({"kind": "basket"}))
    if re.search(r"\b(inventory|pantry|groceries)\b", t):
        return _speak_house(tool_house({"kind": "inventory"}))
    if re.search(r"\b(due|reminders?)\b", t):
        due = tool_due()
        open_rows = due.get("open") or []
        if not open_rows:
            return "Nothing due right now. /reminders/"
        return "Due:\n" + "\n".join(f"· {ln}" for ln in open_rows)
    return None


def _speak_tool_notes(notes: list) -> str:
    bits = []
    for n in notes:
        r = n.get("result") or {}
        if n.get("tool") == "house":
            bits.append(_speak_house(r))
            continue
        if r.get("items"):
            bits.extend(str(x) for x in r["items"])
        elif r.get("lines"):
            bits.append(_speak_house(r))
        elif r.get("need"):
            bits.append(str(r.get("hint") or ("Need: " + ", ".join(str(x) for x in r["need"]))))
        elif r.get("error"):
            bits.append(str(r["error"]))
        elif r.get("ok") and (r.get("href") or r.get("title") or r.get("name")):
            bits.append(str(r.get("title") or r.get("name") or "Saved.") + (f" {r.get('href')}" if r.get("href") else ""))
    return "\n".join(b for b in bits if b).strip()


def _item_line(item) -> str:
    from app.utils.scan import qty_label

    name = getattr(item, "name", None) or "item"
    kind = getattr(item, "item_type", None) or ""
    loc = ""
    qty = ""
    g = getattr(item, "grocery", None)
    if g is not None:
        loc = getattr(g, "default_location", None) or ""
        try:
            qty = qty_label(getattr(g, "quantity", None))
        except Exception:
            qty = ""
    href = _path("items.detail", item_id=item.id)
    bits = [name]
    if kind:
        bits.append(kind)
    if loc:
        bits.append(loc)
    if qty:
        bits.append(str(qty))
    if href:
        bits.append(href)
    return " · ".join(str(b) for b in bits if b)


def tool_find(q: str) -> dict:
    from app.utils.household import household_id
    from app.utils.search import search_household

    needle = _trim(q, 80)
    if len(needle) < 2:
        return {"ok": False, "error": "Need a search of at least two letters."}
    hid = household_id()
    hits = search_household(hid, needle, user_id=current_user.id, limit=12)
    items = [_item_line(i) for i in (hits.get("item_rows") or [])[:10]]
    parts = []
    where = hits.get("part_where") or {}
    for p in (hits.get("part_rows") or [])[:8]:
        host = (where.get(p.id) or "").strip()
        href = _path("items.detail", item_id=p.vehicle_item_id)
        parts.append(" · ".join(b for b in (p.name, host, href) if b))
    notes = []
    for n in (hits.get("note_rows") or [])[:6]:
        href = _path("notes.index")
        notes.append(f"{n.title or 'Note'} · {href}")
    legal = []
    for r in (hits.get("legal_rows") or [])[:5]:
        href = _path("legal.detail", record_id=r.id) if hasattr(r, "id") else _path("legal.index")
        legal.append(f"{r.title or r.kind or 'Record'} · {href}")
    if not (items or parts or notes or legal):
        return {
            "ok": True,
            "q": needle,
            "found": [],
            "hint": f"Nothing stored matches that. Try /find/?q={needle}",
        }
    return {
        "ok": True,
        "q": needle,
        "items": items,
        "parts": parts,
        "notes": notes,
        "records": legal,
        "find": f"/find/?q={needle}",
    }


def tool_due() -> dict:
    from app.utils.household import household_id, scoped
    from app.builddb.table_reminders import Reminder

    rows = (
        scoped(Reminder)
        .filter_by(status="open")
        .order_by(Reminder.due_at.asc(), Reminder.id.desc())
        .limit(12)
        .all()
    )
    out = []
    for r in rows:
        due = r.due_at.strftime("%Y-%m-%d") if r.due_at else "no date"
        out.append(f"{r.title} · {due} · {_path('reminders.index')}")
    return {"ok": True, "open": out, "href": "/reminders/"}


def _vault_guard() -> dict | None:
    from app.utils.password_vault import can_use_vault, is_child, reauth_ok

    if is_child() or not can_use_vault():
        return {"ok": False, "error": "Kids cannot use the vault."}
    if not reauth_ok():
        return {
            "ok": False,
            "need": "vault_unlock",
            "error": "Vault is locked. Open /vault/ with this login first, then ask again.",
        }
    return None


def tool_lookup(args: dict) -> dict:
    upc = _trim(args.get("upc") or args.get("barcode") or args.get("code") or args.get("sn"), 48)
    vin = _trim(args.get("vin"), 32).upper()
    plate = _trim(args.get("plate"), 20).upper()
    if vin or plate:
        from app.utils.vehicle_lookup import lookup_vehicle

        decoded = lookup_vehicle(plate=plate, vin=vin)
        facts = decoded.get("facts") or {}
        return {
            "ok": bool(decoded.get("ok")),
            "kind": "vehicle",
            "vin": decoded.get("vin") or vin,
            "plate": decoded.get("plate") or plate,
            "name": decoded.get("name") or " ".join(
                str(facts.get(k) or "") for k in ("year", "make", "model", "trim") if facts.get(k)
            ).strip(),
            "facts": facts,
            "need_vin": bool(decoded.get("need_vin")),
            "error": decoded.get("error") or decoded.get("message") or "",
        }
    if len(upc) < 8:
        return {"ok": False, "error": "Need a UPC/barcode (8+ digits) or a VIN/plate."}
    from app.utils.barcode_lookup import lookup_product

    hit = lookup_product(upc)
    return {
        "ok": bool(hit.get("ok")),
        "kind": hit.get("kind") or "unknown",
        "kind_label": hit.get("kind_label") or "",
        "suggested_type": hit.get("suggested_type") or "grocery",
        "name": hit.get("name") or "",
        "brand": hit.get("brand") or "",
        "size": hit.get("size") or hit.get("quantity") or "",
        "barcode": hit.get("barcode") or upc,
        "image_url": hit.get("image_url") or "",
        "location_hint": hit.get("location_hint") or "",
        "error": "" if hit.get("ok") else "No catalog hit for that code.",
    }


def tool_vault_unlock(args: dict) -> dict:
    from app.utils.password_vault import can_use_vault, confirm_app_login, is_child, mark_reauth, reauth_ok

    if is_child() or not can_use_vault():
        return {"ok": False, "error": "Kids cannot use the vault."}
    if reauth_ok():
        return {"ok": True, "already": True, "message": "Vault is already open."}
    password = args.get("password") or args.get("secret") or ""
    username = _trim(args.get("username") or getattr(current_user, "username", ""), 80)
    if not confirm_app_login(current_user, username=username, password=str(password)):
        return {
            "ok": False,
            "need": "vault_unlock",
            "error": "That is not this login. Use your Family OS username and password.",
        }
    mark_reauth()
    return {"ok": True, "message": "Vault is open for this session."}


def tool_vault_list(q: str = "") -> dict:
    blocked = _vault_guard()
    if blocked:
        return blocked
    from sqlalchemy.orm import selectinload
    from app.builddb.table_vault_entries import VaultEntry
    from app.utils.household import scoped
    from app.utils.password_vault import can_view_entry, kind_label, open_fields, share_label

    needle = _trim(q, 80).lower()
    rows = (
        scoped(VaultEntry)
        .options(selectinload(VaultEntry.grants))
        .order_by(VaultEntry.updated_at.desc())
        .limit(80)
        .all()
    )
    out = []
    for row in rows:
        if not can_view_entry(row, current_user):
            continue
        fields = open_fields(row)
        title = fields.get("title") or "Untitled"
        blob = " ".join(
            [
                title,
                fields.get("url") or "",
                fields.get("purpose") or "",
                fields.get("login") or "",
                kind_label(row),
            ]
        ).lower()
        if needle and needle not in blob:
            continue
        out.append(
            {
                "id": row.id,
                "title": title,
                "kind": kind_label(row),
                "share": share_label(row.share_mode),
                "site": (fields.get("url") or "")[:120],
                "href": _path("vault.detail", entry_id=row.id) or f"/vault/{row.id}",
            }
        )
        if len(out) >= 12:
            break
    return {"ok": True, "entries": out, "vault": "/vault/"}


def tool_vault_open(entry_id) -> dict:
    blocked = _vault_guard()
    if blocked:
        return blocked
    from sqlalchemy.orm import selectinload
    from app.builddb.table_vault_entries import VaultEntry
    from app.utils.household import scoped
    from app.utils.password_vault import (
        can_view_entry,
        kind_label,
        open_fields,
        share_label,
        two_factor_label,
    )

    if not str(entry_id or "").isdigit():
        return {"ok": False, "error": "Need a vault id from vault_list."}
    row = (
        scoped(VaultEntry)
        .options(selectinload(VaultEntry.grants))
        .filter_by(id=int(entry_id))
        .first()
    )
    if row is None or not can_view_entry(row, current_user):
        return {"ok": False, "error": "That vault card is not visible to you."}
    f = open_fields(row)
    return {
        "ok": True,
        "id": row.id,
        "kind": kind_label(row),
        "share": share_label(row.share_mode),
        "title": f.get("title") or "",
        "url": f.get("url") or "",
        "phone": f.get("phone") or "",
        "account_no": f.get("account_no") or "",
        "login": f.get("login") or "",
        "secret": f.get("secret") or "",
        "two_factor": two_factor_label(f.get("two_factor") or "") or (f.get("two_factor") or ""),
        "two_factor_detail": f.get("two_factor_detail") or "",
        "call_info": f.get("call_info") or "",
        "purpose": f.get("purpose") or "",
        "details": f.get("details") or "",
        "href": _path("vault.detail", entry_id=row.id) or f"/vault/{row.id}",
    }


def tool_vault_save(args: dict) -> dict:
    blocked = _vault_guard()
    if blocked:
        return blocked
    from app.builddb.table_vault_entries import VaultEntry
    from app.utils.household import household_id
    from app.utils.password_vault import SHARE_MODES, kind_of, seal_fields

    title = _trim(args.get("title"), 200)
    if not title:
        return {"ok": False, "error": "Need a title for the vault card."}
    kind = kind_of(args.get("kind") or "password")
    share = _trim(args.get("share") or "personal", 20).lower()
    if share not in SHARE_MODES or share == "selected":
        share = "personal"
    fields = {
        "title": title,
        "login": _trim(args.get("login"), 300),
        "secret": _trim(args.get("secret") or args.get("password"), 500),
        "url": _trim(args.get("url") or args.get("site"), 500),
        "purpose": _trim(args.get("purpose"), 500),
        "details": _trim(args.get("details"), 4000),
        "phone": _trim(args.get("phone"), 80),
        "phone_alt": _trim(args.get("phone_alt"), 80),
        "account_no": _trim(args.get("account_no") or args.get("account"), 200),
        "two_factor": _trim(args.get("two_factor"), 20),
        "two_factor_detail": _trim(args.get("two_factor_detail"), 1000),
        "call_info": _trim(args.get("call_info") or args.get("codes"), 4000),
    }
    hid = household_id()
    sealed = seal_fields(fields, hid)
    entry_id = args.get("id")
    row = None
    if entry_id and str(entry_id).isdigit():
        from sqlalchemy.orm import selectinload
        from app.utils.household import scoped
        from app.utils.password_vault import can_manage_entry

        row = (
            scoped(VaultEntry)
            .options(selectinload(VaultEntry.grants))
            .filter_by(id=int(entry_id))
            .first()
        )
        if row is None or not can_manage_entry(row, current_user):
            return {"ok": False, "error": "You cannot change that vault card."}
        for key, val in sealed.items():
            setattr(row, key, val)
        row.kind = kind
        row.share_mode = share
        row.updated_at = _utcnow()
    else:
        row = VaultEntry(
            household_id=hid,
            created_by=current_user.id,
            kind=kind,
            share_mode=share,
            **sealed,
        )
        db.session.add(row)
    db.session.commit()
    href = _path("vault.detail", entry_id=row.id) or f"/vault/{row.id}"
    return {
        "ok": True,
        "id": row.id,
        "title": title,
        "kind": kind,
        "share": share,
        "href": href,
        "did": "updated" if entry_id else "saved",
    }


def _pin_note_item(args: dict):
    raw = args.get("item_id")
    name = _trim(args.get("item") or args.get("on") or "", 200)
    if not raw and not name:
        return None
    from app.builddb.table_items import Item
    from app.utils.household import household_id

    hid = household_id()
    if raw and str(raw).isdigit():
        item = Item.query.filter_by(id=int(raw), household_id=hid).filter(Item.removed_at.is_(None)).first()
        if item is None:
            return {"ok": False, "error": "That item is not in this household."}
        return item.id
    seen = []
    for kind in ("vehicle", "tool", "house"):
        for row in _find_items(name, kind, limit=4):
            if all(row.id != old.id for old in seen):
                seen.append(row)
    if len(seen) == 1:
        return seen[0].id
    if len(seen) > 1:
        return {
            "ok": False,
            "need": ["item"],
            "choices": [r.name for r in seen],
            "hint": "Which one should this note sit on? " + ", ".join(r.name for r in seen),
        }
    return {"ok": False, "error": f"No vehicle, tool, or equipment named {name}."}


def tool_note_save(args: dict) -> dict:
    from sqlalchemy import or_
    from app.builddb.table_notes import VISIBILITY, Note
    from app.utils.household import household_id, scoped

    hid = household_id()
    vis = _trim(args.get("share") or args.get("visibility") or "", 20).lower()
    if vis == "house":
        vis = "household"
    body = _trim(args.get("body") or args.get("text"), 8000)
    title = _trim(args.get("title"), 500)
    note = None
    raw_id = args.get("id")
    if raw_id and str(raw_id).isdigit():
        note = scoped(Note).filter_by(id=int(raw_id)).first()
        if note is None:
            return {"ok": False, "error": "No note with that id."}
        if note.user_id != current_user.id and not getattr(current_user, "is_admin", False):
            return {"ok": False, "error": "You cannot change that note."}
    elif title:
        note = (
            scoped(Note)
            .filter(or_(Note.visibility == "household", Note.user_id == current_user.id))
            .filter(Note.title == title)
            .order_by(Note.id.desc())
            .first()
        )
        if note is not None and note.user_id != current_user.id and not getattr(current_user, "is_admin", False):
            note = None
    pinned = _pin_note_item(args)
    if isinstance(pinned, dict):
        return pinned
    if note is None:
        if not title:
            return {"ok": False, "error": "Need a note title."}
        if vis not in VISIBILITY:
            vis = "personal"
        note = Note(
            household_id=hid,
            user_id=current_user.id,
            visibility=vis,
            title=title,
            body=body or None,
            item_id=pinned,
        )
        db.session.add(note)
        db.session.commit()
        href = f"/items/{pinned}?tab=notes" if pinned else "/notes/"
        return {"ok": True, "id": note.id, "title": title, "share": vis, "href": href, "did": "saved"}
    if title:
        note.title = title
    if body:
        note.body = ((note.body or "") + "\n" + body).strip() if args.get("append") else body
    if vis in VISIBILITY:
        note.visibility = vis
    if pinned:
        note.item_id = pinned
    db.session.commit()
    return {
        "ok": True,
        "id": note.id,
        "title": note.title,
        "share": note.visibility,
        "href": f"/items/{note.item_id}?tab=notes" if note.item_id else "/notes/",
        "did": "updated",
    }


def _basket_names(args: dict) -> list[str]:
    names = []
    raw = args.get("names") or args.get("items") or []
    if isinstance(raw, str):
        raw = [p.strip() for p in raw.replace("\n", ",").split(",")]
    if isinstance(raw, list):
        names.extend(_trim(n, 200) for n in raw)
    one = _trim(args.get("name") or args.get("title"), 200)
    if one:
        if "," in one and not names:
            names.extend(_trim(p, 200) for p in one.split(","))
        else:
            names.insert(0, one)
    out = []
    for n in names:
        if n and n not in out:
            out.append(n)
    return out[:40]


def tool_basket_add(args: dict) -> dict:
    if not (can("scan") or can("edit_grocery")):
        return {"ok": False, "error": "You cannot add to the basket."}
    from app.builddb.table_grocery_list import GroceryListEntry
    from app.utils.household import household_id

    names = _basket_names(args)
    if not names:
        return {"ok": False, "error": "Need a name to put on the basket."}
    store = _trim(args.get("store") or args.get("from") or args.get("note"), 120) or None
    hid = household_id()
    added = []
    for name in names:
        db.session.add(
            GroceryListEntry(
                household_id=hid,
                name=name,
                status="open",
                added_reason="want",
                note=store,
                created_by=current_user.id,
            )
        )
        added.append(name)
    db.session.commit()
    return {
        "ok": True,
        "names": added,
        "store": store or "",
        "href": "/groceries/list",
        "did": f"added {len(added)}",
    }


def tool_basket_match(args: dict) -> dict:
    if not (can("scan") or can("edit_grocery")):
        return {"ok": False, "error": "You cannot change the basket."}
    from app.builddb.table_grocery_list import GroceryListEntry
    from app.builddb.table_items import Item
    from app.utils.basket_match import apply_match, suggest_for_item, suggest_for_text
    from app.utils.household import household_id, scoped

    hid = household_id()
    entry_id = args.get("entry_id") or args.get("id")
    item_id = args.get("item_id")
    if entry_id and str(entry_id).isdigit() and item_id and str(item_id).isdigit():
        row = scoped(GroceryListEntry).filter_by(id=int(entry_id)).first()
        item = Item.query.filter_by(id=int(item_id), household_id=hid).first()
        if row is None or item is None:
            return {"ok": False, "error": "Need a basket row and an item in this house."}
        result = apply_match(row, item, current_user.id, restock=True)
        db.session.commit()
        return result
    q = _trim(args.get("q") or args.get("name") or args.get("item"), 200)
    item = None
    if item_id and str(item_id).isdigit():
        item = Item.query.filter_by(id=int(item_id), household_id=hid).first()
    elif q:
        found = _find_items(q, "grocery", limit=3)
        item = found[0] if found else None
    if item is not None:
        hit = suggest_for_item(hid, item, min_score=0.5)
        if hit and args.get("apply"):
            row = scoped(GroceryListEntry).filter_by(id=hit["id"]).first()
            if row:
                result = apply_match(row, item, current_user.id, restock=True)
                db.session.commit()
                return result
        return {"ok": True, "item_id": item.id, "name": item.name, "match": hit, "href": "/groceries/list"}
    if q:
        return {"ok": True, "suggestions": suggest_for_text(hid, q), "href": "/groceries/list"}
    return {"ok": False, "error": "Say which basket row and which scanned item."}


def _parse_due(raw: str):
    text = _trim(raw, 32)
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text[:16], fmt)
        except ValueError:
            continue
    return None


def _every_key(raw: str) -> str | None:
    from app.utils.reminders_copy import parse_recurrence

    key = _trim(raw, 40).lower().replace(" ", "")
    aliases = {
        "monthly": "30d",
        "month": "30d",
        "everymonth": "30d",
        "yearly": "365d",
        "year": "365d",
        "annual": "365d",
        "quarterly": "90d",
        "every3months": "90d",
        "every6months": "180d",
    }
    key = aliases.get(key, key)
    return parse_recurrence(key)


def tool_reminder_save(args: dict) -> dict:
    if not can("maintain"):
        return {"ok": False, "error": "You cannot add a reminder."}
    from app.builddb.table_reminders import Reminder
    from app.utils.household import household_id
    from app.utils.notify import announce_reminder
    from app.utils.reminders_copy import REMINDER_TYPES

    title = _trim(args.get("title"), 200)
    if not title:
        return {"ok": False, "error": "Need a reminder title."}
    rtype = _trim(args.get("type") or args.get("kind") or "custom", 40).lower()
    if rtype in ("billing", "bill", "utility"):
        rtype = "bill"
    allowed = {k for k, _lab in REMINDER_TYPES}
    if rtype not in allowed:
        rtype = "custom"
    due_at = _parse_due(args.get("due") or args.get("due_at") or "")
    rec = _every_key(args.get("every") or args.get("recurrence") or "")
    notes = _trim(args.get("notes") or args.get("account") or args.get("account_no"), 500)
    row = Reminder(
        household_id=household_id(),
        title=title,
        type=rtype,
        due_at=due_at,
        recurrence=rec,
        notes=notes or None,
        status="open",
        created_by=current_user.id,
    )
    db.session.add(row)
    db.session.flush()
    try:
        announce_reminder(row)
    except Exception:
        pass
    db.session.commit()
    return {
        "ok": True,
        "id": row.id,
        "title": title,
        "type": rtype,
        "due": due_at.strftime("%Y-%m-%d") if due_at else None,
        "every": rec or "once",
        "href": "/reminders/",
    }


def tool_inventory(args: dict) -> dict:
    from app.routes.items import can_create_type, quick_create_item
    from app.utils.household import household_id
    from app.utils.scan import apply_grocery_stock, flag_need_more, qty_label

    action = _trim(args.get("action") or "restock", 20).lower()
    if action in ("add", "new", "buy"):
        action = "create"
    if action in ("out", "consume", "use"):
        action = "used"
    if action in ("need_more", "low"):
        action = "need"
    q = _trim(args.get("q") or args.get("name") or args.get("id"), 200)
    upc = _trim(args.get("upc") or args.get("barcode"), 48)
    amount = args.get("amount") or args.get("qty") or 1
    place = _trim(args.get("place") or args.get("location"), 80)
    hid = household_id()
    if action == "create":
        if not can_create_type("grocery"):
            return {"ok": False, "error": "You cannot add inventory."}
        name = q or "Item"
        item, status = quick_create_item(
            hid=hid,
            user_id=current_user.id,
            name=name,
            item_type="grocery",
            barcode=upc or None,
            location=place or None,
            quantity=amount,
            action="restock",
        )
        if item is None:
            return {"ok": False, "error": status or "Could not add that."}
        if status == "exists":
            g = item.grocery
            if g is not None:
                apply_grocery_stock(g, item, "restock", amount, current_user.id, place=place or None)
                db.session.commit()
            return {
                "ok": True,
                "id": item.id,
                "name": item.name,
                "did": "already had it · restocked",
                "href": _path("items.detail", item_id=item.id),
            }
        return {
            "ok": True,
            "id": item.id,
            "name": item.name,
            "did": "saved",
            "href": _path("items.detail", item_id=item.id),
        }
    rows = _find_items(q, "grocery")
    if not rows:
        return {"ok": False, "error": f"Nothing in inventory matches {q or 'that'}. Use action create to add it."}
    item = rows[0]
    g = item.grocery
    if g is None:
        return {"ok": False, "error": f"{item.name} is not an inventory row."}
    if action == "need":
        flag_need_more(g, item, current_user.id)
        db.session.commit()
        return {
            "ok": True,
            "id": item.id,
            "name": item.name,
            "did": "need more · on the basket",
            "href": _path("items.detail", item_id=item.id),
        }
    stock_action = "set" if action == "set" else ("restock" if action == "restock" else "consume")
    apply_grocery_stock(g, item, stock_action, amount, current_user.id, place=place or None)
    db.session.commit()
    return {
        "ok": True,
        "id": item.id,
        "name": item.name,
        "qty": qty_label(g.quantity),
        "did": action,
        "href": _path("items.detail", item_id=item.id),
    }


def tool_tool_save(args: dict) -> dict:
    from app.routes.items import can_create_type, quick_create_item
    from app.builddb.table_tools import Tool
    from app.utils.household import household_id
    from app.utils.qr_labels import item_payload

    if not can_create_type("tool"):
        return {"ok": False, "error": "You cannot add tools."}
    name = _trim(args.get("name"), 200)
    barcode = _trim(args.get("barcode") or args.get("upc"), 48)
    model = _trim(args.get("model"), 120)
    serial = _trim(args.get("serial") or args.get("serial_number") or args.get("sn"), 120)
    tool_type = _trim(args.get("type") or args.get("kind"), 80)
    notes = _trim(args.get("notes"), 2000)
    if barcode and not name:
        from app.utils.barcode_lookup import lookup_product

        hit = lookup_product(barcode)
        name = _trim(hit.get("name") or hit.get("brand"), 200)
    if not name:
        return {"ok": False, "error": "Need a tool name, or a UPC to look up."}
    hid = household_id()
    existing = _find_items(name, "tool", limit=1)
    if existing and not args.get("force"):
        item = existing[0]
        t = item.tool
        if t is None:
            t = Tool(item_id=item.id, household_id=hid)
            db.session.add(t)
        if tool_type:
            t.type = tool_type
        if model:
            t.model = model
        if serial:
            t.serial_number = serial
        if notes:
            t.usage_notes = notes
        if barcode:
            item.barcode = barcode
        db.session.commit()
        return {
            "ok": True,
            "id": item.id,
            "name": item.name,
            "did": "updated",
            "href": _path("items.detail", item_id=item.id),
        }
    item, status = quick_create_item(
        hid=hid,
        user_id=current_user.id,
        name=name,
        item_type="tool",
        barcode=barcode or None,
        kind=tool_type or None,
        kind_label=tool_type or None,
    )
    if item is None:
        return {"ok": False, "error": status or "Could not save the tool."}
    t = item.tool
    if t is None:
        t = Tool(item_id=item.id, household_id=hid, type=tool_type or None)
        db.session.add(t)
    t.type = tool_type or t.type
    t.model = model or t.model
    t.serial_number = serial or t.serial_number
    t.usage_notes = notes or t.usage_notes
    if not item.barcode:
        item.barcode = item_payload(hid, item.id)
    db.session.commit()
    return {
        "ok": True,
        "id": item.id,
        "name": item.name,
        "did": "saved" if status == "ok" else status,
        "href": _path("items.detail", item_id=item.id),
    }


def tool_vehicle_save(args: dict) -> dict:
    from app.routes.items import can_create_type
    from app.builddb.table_items import Item
    from app.builddb.table_vehicles import Vehicle
    from app.utils.household import household_id
    from app.utils.qr_labels import item_payload
    from app.utils.vehicle_lookup import apply_vehicle_lookup, lookup_vehicle

    if not can_create_type("vehicle"):
        return {"ok": False, "error": "You cannot add vehicles."}
    plate = _trim(args.get("plate"), 20).upper()
    vin = _trim(args.get("vin"), 32).upper()
    typed_name = _trim(args.get("name"), 200)
    make = _trim(args.get("make"), 80)
    model = _trim(args.get("model"), 80)
    year = _trim(args.get("year"), 8)
    if not (plate or vin or typed_name or make or model):
        return {"ok": False, "error": "Need a VIN, plate, or name."}
    hid = household_id()
    if vin:
        clash = Vehicle.query.filter_by(household_id=hid).filter(Vehicle.vin == vin).first()
        if clash:
            return {
                "ok": True,
                "id": clash.item_id,
                "did": "already had that VIN",
                "href": _path("items.detail", item_id=clash.item_id),
            }
    decoded = lookup_vehicle(plate=plate, vin=vin) if (plate or vin) else {"ok": True, "facts": {}, "recalls": []}
    facts = decoded.get("facts") or {}
    name = (
        typed_name
        or decoded.get("name")
        or " ".join(x for x in (year or facts.get("year"), make or facts.get("make"), model or facts.get("model")) if x)
        or (f"Plate {plate}" if plate else None)
        or (f"VIN {vin[:8]}" if vin else "Vehicle")
    )
    item = Item(
        household_id=hid,
        name=str(name)[:200],
        item_type="vehicle",
        created_by=current_user.id,
    )
    db.session.add(item)
    db.session.flush()
    item.barcode = item_payload(hid, item.id)
    v = Vehicle(item_id=item.id, household_id=hid)
    db.session.add(v)
    apply_vehicle_lookup(v, item, decoded)
    if make:
        v.make = make
    if model:
        v.model = model
    if year.isdigit():
        v.year = int(year)
    if plate:
        v.plate = plate[:20]
    if vin:
        v.vin = vin[:32]
    db.session.commit()
    return {
        "ok": True,
        "id": item.id,
        "name": item.name,
        "did": "saved",
        "need_vin": bool(decoded.get("need_vin")),
        "href": _path("items.detail", item_id=item.id),
    }


def run_tool(name: str, args: dict | None) -> dict:
    args = args if isinstance(args, dict) else {}
    key = (name or "").strip().lower()
    try:
        if key == "find":
            return tool_find(args.get("q") or args.get("query") or "")
        if key == "house":
            return tool_house(args)
        if key == "due":
            return tool_due()
        if key == "lookup":
            return tool_lookup(args)
        if key == "vault_unlock":
            return tool_vault_unlock(args)
        if key == "vault_list":
            return tool_vault_list(args.get("q") or "")
        if key == "vault_open":
            return tool_vault_open(args.get("id") or args.get("entry_id"))
        if key == "vault_save":
            return tool_vault_save(args)
        if key == "note_save":
            return tool_note_save(args)
        if key == "basket_add":
            return tool_basket_add(args)
        if key == "basket_match":
            return tool_basket_match(args)
        if key == "reminder_save":
            return tool_reminder_save(args)
        if key == "inventory":
            return tool_inventory(args)
        if key == "tool_save":
            return tool_tool_save(args)
        if key == "vehicle_save":
            return tool_vehicle_save(args)
        if key == "place":
            from app.utils.ask_do import tool_place

            return tool_place(args)
        if key == "guide":
            from app.utils.ask_do import tool_guide

            return tool_guide(args)
        if key == "member_add":
            from app.utils.ask_do import tool_member_add

            return tool_member_add(args)
        if key == "member_list":
            from app.utils.ask_do import tool_member_list

            return tool_member_list(args)
        if key == "member_role":
            from app.utils.ask_do import tool_member_role

            return tool_member_role(args)
        if key == "part_save":
            from app.utils.ask_do import tool_part_save

            return tool_part_save(args)
        if key == "log_save":
            from app.utils.ask_do import tool_log_save

            return tool_log_save(args)
        if key == "legal_save":
            from app.utils.ask_do import tool_legal_save

            return tool_legal_save(args)
        if key == "oil_save":
            from app.utils.ask_do import tool_oil_save

            return tool_oil_save(args)
    except Exception as exc:
        return {"ok": False, "error": f"Could not do that: {exc}"}
    return {"ok": False, "error": f"Unknown tool {name}."}


def _parse_turn(text: str) -> dict:
    parsed = parse_json_object(text or "")
    if isinstance(parsed, dict):
        tool = (parsed.get("tool") or "").strip().lower()
        if tool in TOOLS:
            args = parsed.get("args") if isinstance(parsed.get("args"), dict) else {}
            if not args:
                args = {k: v for k, v in parsed.items() if k not in ("tool", "say")}
            return {"kind": "tool", "tool": tool, "args": args}
        if "say" in parsed:
            return {"kind": "say", "text": _trim(parsed.get("say"), 4000)}
    raw = (text or "").strip()
    return {"kind": "say", "text": raw[:4000]} if raw else {"kind": "say", "text": ""}


def _prompt_for(history: list, message: str, tool_notes: list) -> str:
    bits = []
    for row in history[-8:]:
        role = "You" if row.get("role") == "assistant" else "Them"
        bits.append(f"{role}: {_trim(row.get('text'), 800)}")
    bits.append(f"Them: {_trim(message, MSG_CAP)}")
    for note in tool_notes:
        bits.append("Tool result JSON:\n" + json.dumps(note, ensure_ascii=False)[:3500])
    bits.append("Reply with JSON only.")
    return "\n\n".join(bits)


PHOTO_TOOLS = ("place", "part_save", "tool_save", "vehicle_save", "inventory", "note_save", "legal_save")
PHOTO_ASK = (
    "Look at this photo. Read any barcode, serial, VIN, model, or part number. "
    "If there is no code, identify the tool, part, or item and put it in the right place."
)


def _system_now(has_photo: bool) -> str:
    from app.utils.ask_do import PHOTO_RULES, actor_lines

    extra = actor_lines()
    if has_photo:
        extra += "\n\n" + PHOTO_RULES
    return SYSTEM + "\n\n" + extra


def _with_issued_login(say: str, tool_notes: list) -> str:
    text = say or ""
    for note in tool_notes:
        if note.get("tool") != "member_add":
            continue
        result = note.get("result") or {}
        password = result.get("password") or ""
        username = result.get("username") or ""
        if not result.get("ok") or not password or password in text:
            continue
        text = text.rstrip() + f"\nUsername {username}. Password {password}. They sign in with the household handle."
    return text


def run_ask(message: str, *, household, image_bytes: bytes | None = None, image_mime: str | None = None) -> dict:
    from app.utils.ask_photo import (
        attach_pending,
        clear_ask_photo,
        load_ask_photo,
        photo_was_attached,
        stash_ask_photo,
    )

    text = _trim(message, MSG_CAP)
    photo = None
    if image_bytes:
        stash_ask_photo(int(getattr(household, "id", 0) or 0), image_bytes, image_mime or "image/jpeg")
        loaded = load_ask_photo()
        photo = loaded if loaded and loaded[0] else (image_bytes, image_mime or "image/jpeg")
    else:
        photo = load_ask_photo()
    has_photo = bool(photo and photo[0])
    if not text and has_photo:
        text = PHOTO_ASK
    if not text:
        return {"ok": False, "error": "Say something first."}
    if household is None or int(getattr(household, "id", 0) or 0) != int(getattr(current_user, "household_id", 0) or 0):
        return {"ok": False, "error": "AI stays in this household."}
    if not ask_ready(household, current_user):
        return {"ok": False, "error": "Ask is off. Add an AI key in Household, or turn Ask back on."}
    if has_photo:
        from app.utils.ai import get_ai_config

        if not get_ai_config(household, household_only=True).get("vision"):
            clear_ask_photo()
            return {
                "ok": False,
                "error": "This AI key cannot read photos. Use Gemini or Grok in Household, or type the code.",
            }
    if not _rate_ok():
        return {"ok": False, "error": "Give Ask a minute. Too many questions just now."}
    remembered = None if has_photo else _remember_reply(text)
    if remembered:
        history = _history()
        history.append({"role": "user", "text": text})
        history.append({"role": "assistant", "text": remembered.get("say") or ""})
        _save_history(history)
        return remembered
    local = None if has_photo else _local_house_say(text)
    if local:
        history = _history()
        history.append({"role": "user", "text": text})
        history.append({"role": "assistant", "text": local})
        _save_history(history)
        return {"ok": True, "say": local, "did": [], "vault_locked": False}
    history = _history()
    tool_notes = []
    did = []
    last_say = ""
    system = _system_now(has_photo)
    for _ in range(MAX_TOOL_ROUNDS + 1):
        ok, raw = complete(
            _prompt_for(history, text, tool_notes),
            system=system,
            max_tokens=1200 if has_photo else 900,
            timeout=55 if has_photo else 40,
            household=household,
            household_only=True,
            image_bytes=photo[0] if has_photo else None,
            image_mime=(photo[1] if has_photo else None) or "image/jpeg",
        )
        if not ok:
            spoken = _speak_tool_notes(tool_notes) or _local_house_say(text)
            if spoken:
                last_say = spoken
                break
            if re.match(r"^(hi|hello|hey|yo)\b", text, re.I):
                last_say = "Hey. I can look up this house even when the model is busy — try “what tools do I have.”"
                break
            return {"ok": False, "error": raw or "The model is busy. Try “what tools do I have.”"}
        turn = _parse_turn(raw)
        if turn["kind"] == "tool":
            result = run_tool(turn["tool"], turn.get("args"))
            if has_photo and turn["tool"] in PHOTO_TOOLS:
                try:
                    if attach_pending(turn["tool"], result):
                        result["photo"] = "attached"
                except Exception:
                    pass
            tool_notes.append({"tool": turn["tool"], "result": result})
            if result.get("ok") and turn["tool"] in WRITE_TOOLS:
                did.append(
                    {
                        "tool": turn["tool"],
                        "href": result.get("href") or "",
                        "title": result.get("title") or result.get("name") or "",
                    }
                )
            continue
        last_say = (turn.get("text") or "").strip()
        if not last_say and tool_notes:
            last_say = _speak_tool_notes(tool_notes)
        break
    if not last_say:
        last_say = _speak_tool_notes(tool_notes) or _local_house_say(text)
    if not last_say:
        return {
            "ok": False,
            "error": "I didn’t catch that. Try “what tools do I have” or “what’s due.”",
        }
    last_say = _with_issued_login(last_say, tool_notes)
    if photo_was_attached():
        clear_ask_photo()
    history.append({"role": "user", "text": text})
    history.append({"role": "assistant", "text": last_say})
    _save_history(history)
    return {"ok": True, "say": last_say, "did": did, "vault_locked": any((n.get("result") or {}).get("need") == "vault_unlock" for n in tool_notes)}
