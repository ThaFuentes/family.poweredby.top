"""Household Ask: talk to the household AI and let it look up or do work.

Uses the household BYOK key only. Kids never see it. Vault reads and writes
need the vault unlocked for this login.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date, datetime, timedelta

from flask import g, has_request_context, session, url_for
from flask_login import current_user

from app.builddb.builddb import db
from app.utils.ai import complete, parse_json_object
from app.utils.household_ai import ask_available
from app.utils.permissions import can, role_of

SESSION_HISTORY = "family_ask_history"
SESSION_HITS = "family_ask_hits"
SESSION_OIL_PENDING = "family_ask_oil_pending"
SESSION_EXPIRE_PENDING = "family_ask_expire_pending"
SESSION_ITEM_PENDING = "family_ask_item_pending"
SESSION_REMOVE_PENDING = "family_ask_remove_pending"
MAX_HISTORY = 24
MAX_TOOL_ROUNDS = 6
MAX_HITS = 40
HIT_WINDOW = 600
MSG_CAP = 2000
TURN_KEEP = 80
IDLE_DAYS = 14

TOOLS = (
    "find",
    "house",
    "due",
    "vehicle_card",
    "item_inspect",
    "item_remove",
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
    "member_password",
    "member_remove",
    "part_save",
    "log_save",
    "trip_save",
    "legal_save",
    "oil_save",
    "oil_lookup",
    "expire_list",
    "expire_save",
    "expire_guess",
    "inventory_sort",
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
    "member_password",
    "member_remove",
    "part_save",
    "log_save",
    "trip_save",
    "legal_save",
    "oil_save",
    "item_remove",
    "expire_save",
    "expire_guess",
    "inventory_sort",
)

SYSTEM = """You are Ask in Family OS. Do the house work this person is already allowed to do: people, tools, parts, vehicles, the house, notes, inventory, basket, logs, legal paper, photos, oil specs, food dates, and (only when unlocked) the vault.

You look things up on this site yourself with find and item_inspect. Never tell them to go look, type a VIN, or open a page to read a field you can inspect.

Reply with ONE JSON object per turn.
To act: {"tool":"find","args":{"q":"gas generator"}}
To talk: {"say":"short spoken English with /items/4 links."}
The say field is spoken English only. Never put JSON, tool names, or raw tool results in say.

{"tool":"find","args":{"q":"batteries"}}
{"tool":"item_inspect","args":{"q":"gas gen"}}
{"tool":"item_remove","args":{"q":"old drill"}}
{"tool":"house","args":{"kind":"tools"}}
{"tool":"house","args":{"kind":"vehicles"}}
{"tool":"vehicle_card","args":{"q":"2006 tundra"}}
{"tool":"house","args":{"kind":"basket"}}
{"tool":"due","args":{}}
{"tool":"expire_list","args":{"days":21}}
{"tool":"expire_save","args":{"q":"milk","date":"2026-10-04","amount":1,"place":"fridge"}}
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
{"tool":"member_password","args":{"username":"sam","password":""}}
{"tool":"member_remove","args":{"username":"sam"}}
{"tool":"log_save","args":{"item":"Silverado","kind":"miles","reading":"81200","notes":""}}
{"tool":"trip_save","args":{"item":"blue tundra","action":"start","reading":"81200","origin":"Odessa","dest":"Lubbock"}}
{"tool":"trip_save","args":{"item":"blue tundra","action":"end","reading":"81650"}}
{"tool":"oil_save","args":{"item":"Honda generator","needs":"SAE 10W-30","capacity":"20 oz","in_it":"","last_date":"","interval_hours":"50","interval_months":"6"}}
{"tool":"oil_lookup","args":{"q":"white tundra 2011"}}
{"tool":"expire_list","args":{"days":21}}
{"tool":"expire_guess","args":{}}
{"tool":"inventory_sort","args":{"only_empty":"1"}}
{"tool":"note_save","args":{"title":"Spare key","body":"In the kitchen drawer.","item":"Silverado","share":"household"}}
{"tool":"legal_save","args":{"title":"Parking ticket","kind":"ticket","agency":"","due":"","amount":"","body":""}}
{"tool":"guide","args":{"action":"add_person"}}

place what: tool, part, grocery, vehicle, house, note, legal.
A photo with a barcode, VIN, or serial: read the code, then place or lookup. No code: identify the tool or part and place it. Do not invent codes.
Oil: inspect the named vehicle or tool first (gas gen, mower, white tundra 2011). If oil_needs is filled, tell them that spec. If it is empty, call oil_lookup using the saved year/make/model/VIN so the OEM spec is looked up, tell them that spec, and ask if you should oil_save it. Do not ask them to look it up or to paste a VIN.
needs is the Oil it needs field. in_it is what was poured. Do not say the oil was added unless oil_save returns a needs value.
If they say add that, save that, yes, or put that on a vehicle, tool, or the house, save your previous reply on that item with note_save. When the reply is an oil spec, also oil_save with needs set to that spec.
Adding a person: call member_add only when you have a name and username. If either is missing, ask. Role member, admin, or child. Password may be blank.
When member_add returns a password, say the username and password once so they can copy it.
inventory action: restock, used, set, need, create. If the item is not on the site, inventory guesses the room (Fridge, Pantry, …) from the name. Do not ask pantry vs fridge. Confirm the add. Only ask where if grocery vs tools vs a vehicle is actually unclear.
expire_save writes a use-by date on food. expire_list says what is going bad soon and how many food rows have no date. expire_guess writes typical shelf life on those undated rows when they say add generic expirations.
If they say sort / organize / put inventory in rooms, call inventory_sort. That files groceries into Fridge, Pantry, and the other rooms. Do not dump the inventory list. only_empty 1 (default) fills items with no room yet. only_empty 0 re-files everything.
If they name one food and a room (“burritos go in the freezer”) call inventory with action place. If they want a count (“show 2 of these”) call inventory action set with amount. Never dump the whole inventory for that.
item_remove takes a tool, vehicle, or grocery out of the house. Call it with the exact name. Prefer a grocery when they named food (protein bars, milk). Never remove a vehicle unless they named that truck or said truck/car. The tool asks for a yes before it deletes. Do not remove vault cards this way.
vault kind: password, billing, info. share: personal or household.
two_factor: none, sms, app, email, hardware, other.
reminder type: bill, oil_change, filter, custom. every: 30d, 90d, 180d, 365d, 3000mi, 5000mi, 50h, or monthly/yearly.

If they name a store run (Sam's, Costco) put those names on the basket with store set — no barcode yet. When they later scan a product that fits (french vanilla creamer vs coffee creamer), call basket_match so it links and comes off the list.
If vault is locked, call vault_unlock when they gave the password, else tell them to open /vault/ or paste the password.
Look up a UPC/VIN before creating a tool, vehicle, or grocery when they gave a code.
A saved vehicle or tool already has its year, make, model, color, VIN, plate, serial, and oil. Call item_inspect or vehicle_card before you ask for any of those.
Trips: start a trip with trip_save action start (odometer + from/to). End it with action end and the new miles. That updates the truck's miles and the Log tab. "I'm home with 81650 miles" is an end.
The app may queue writes and ask them to allow. A queued result is not saved yet. Do not say you already saved until a tool returns ok without queued.
Do not dump inventory, vehicles, tools, or the basket unless they asked to show, list, or open that. Talking about a truck, sorting food, or doing a job is not a list request. Inspect the named thing instead.
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


def _set_room(room: str | None) -> str:
    from app.utils.ask_rooms import normalize_room

    key = normalize_room(room)
    if has_request_context():
        g.ask_room = key
    return key


def _room() -> str:
    from app.utils.ask_rooms import normalize_room

    if has_request_context():
        return normalize_room(getattr(g, "ask_room", None))
    return "house"


def _sess_key() -> str:
    room = _room()
    if room == "house":
        return SESSION_HISTORY
    return f"{SESSION_HISTORY}:{room}"


def _history() -> list:
    if not has_request_context():
        return []
    stored = _load_turns()
    if stored:
        return stored
    rows = session.get(_sess_key()) or []
    if not isinstance(rows, list) and _room() == "house":
        rows = session.get(SESSION_HISTORY) or []
    if not isinstance(rows, list):
        return []
    return rows[-MAX_HISTORY:]


def _save_history(rows: list) -> None:
    if not has_request_context():
        return
    session[_sess_key()] = rows[-MAX_HISTORY:]
    _store_latest(rows)


def _turn_user():
    if not has_request_context() or not getattr(current_user, "is_authenticated", False):
        return None
    uid = int(getattr(current_user, "id", 0) or 0)
    hid = int(getattr(current_user, "household_id", 0) or 0)
    if not uid or not hid:
        return None
    return uid, hid


def _turn_age_days(row) -> int | None:
    ts = getattr(row, "created_at", None)
    if ts is None:
        return None
    try:
        if getattr(ts, "tzinfo", None) is not None:
            ts = ts.replace(tzinfo=None)
        return max(0, (_utcnow() - ts).days)
    except Exception:
        return None


def _expire_idle_turns(uid: int, hid: int, room: str, newest) -> bool:
    age = _turn_age_days(newest)
    if age is None or age < IDLE_DAYS:
        return False
    try:
        from app.builddb.table_ask_turns import AskTurn

        AskTurn.query.filter_by(household_id=hid, user_id=uid, room=room).delete(
            synchronize_session=False
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        return False
    return True


def _load_turns() -> list:
    who = _turn_user()
    if not who:
        return []
    try:
        from app.builddb.table_ask_turns import AskTurn

        uid, hid = who
        room = _room()
        rows = (
            AskTurn.query.filter_by(household_id=hid, user_id=uid, room=room)
            .order_by(AskTurn.id.desc())
            .limit(TURN_KEEP)
            .all()
        )
        if rows and _expire_idle_turns(uid, hid, room, rows[0]):
            return []
    except Exception:
        return []
    out = []
    for row in reversed(rows):
        text = (row.body or "").strip()
        if text and row.role in ("user", "assistant"):
            out.append({"role": row.role, "text": text[:4000]})
    return out


def history_payload(room: str | None = None) -> dict:
    if room is not None:
        _set_room(room)
    turns = _load_turns()
    return {
        "ok": True,
        "room": _room(),
        "turns": [{"role": row.get("role"), "text": row.get("text") or ""} for row in turns],
    }


def _prune_turns(uid: int, hid: int) -> None:
    from app.builddb.table_ask_turns import AskTurn

    stale = (
        AskTurn.query.filter_by(household_id=hid, user_id=uid, room=_room())
        .order_by(AskTurn.id.desc())
        .offset(TURN_KEEP)
        .all()
    )
    for row in stale:
        db.session.delete(row)


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
        room = _room()
        latest = (
            AskTurn.query.filter_by(household_id=hid, user_id=uid, room=room)
            .order_by(AskTurn.id.desc())
            .limit(2)
            .all()
        )
        last_bodies = [(r.role, (r.body or "").strip()) for r in latest]
        if ("assistant", last_assistant) in last_bodies:
            return
        if last_user:
            db.session.add(
                AskTurn(household_id=hid, user_id=uid, role="user", room=room, body=last_user[:4000])
            )
        db.session.add(
            AskTurn(
                household_id=hid,
                user_id=uid,
                role="assistant",
                room=room,
                body=last_assistant[:4000],
            )
        )
        db.session.flush()
        _prune_turns(uid, hid)
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
        AskTurn.query.filter_by(household_id=hid, user_id=uid, room=_room()).delete(
            synchronize_session=False
        )
        db.session.commit()
    except Exception:
        db.session.rollback()


def clear_history(room: str | None = None) -> None:
    if room is not None:
        _set_room(room)
    if has_request_context():
        session.pop(_sess_key(), None)
        if _room() == "house":
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


_VEHICLE_STOP = {
    "what", "whats", "what’s", "the", "vin", "vins", "from", "my", "our", "site",
    "please", "provide", "your", "can", "you", "find", "look", "up", "lookup",
    "looking", "correct", "oil", "specification", "spec", "section", "already",
    "saved", "have", "has", "show", "tell", "which", "where", "does", "take",
    "need", "needs", "for", "and", "its", "it's", "this", "that", "with", "about",
    "use", "type", "named", "name", "right", "area", "truck", "trucks", "car",
    "cars", "vehicle", "vehicles", "are", "was", "were", "there", "still", "not",
    "finding", "kinda", "kind", "into", "onto", "delete", "remove", "removed",
    "home", "miles", "mile", "trip", "trips", "start", "starting", "begin",
    "ending", "odometer", "odo",
}


def _vehicle_tokens(text: str) -> list[str]:
    out = []
    for tok in re.findall(r"[a-z0-9]+", (text or "").lower()):
        if tok in _VEHICLE_STOP:
            continue
        if len(tok) >= 3 or tok.isdigit():
            out.append(tok)
    return out


def _vehicle_blob(item) -> str:
    vehicle = getattr(item, "vehicle", None)
    parts = [getattr(item, "name", None) or "", getattr(item, "notes", None) or "", getattr(item, "category", None) or ""]
    if vehicle is not None:
        parts.extend(
            str(getattr(vehicle, key) or "")
            for key in ("year", "make", "model", "trim", "color", "vin", "plate", "oil_needs", "oil_type")
        )
        year = str(getattr(vehicle, "year", None) or "")
        if len(year) == 4 and year.isdigit():
            parts.append(year[-2:])
    return " ".join(parts).lower()


def _token_hits(item, tokens: list[str]) -> int:
    blob = _vehicle_blob(item)
    hits = 0
    for tok in tokens:
        if tok in blob:
            hits += 1
            continue
        if tok.isdigit() and len(tok) == 4 and tok[-2:] in blob:
            hits += 1
    return hits


def _matching_vehicles(text: str) -> list:
    """Best saved trucks for this question. Extra words like 'use' and 'type' do not knock a truck out."""
    tokens = _vehicle_tokens(text)
    rows = _find_items("", "vehicle", limit=40)
    if not rows:
        return []
    if not tokens:
        return rows
    scored = [( _token_hits(item, tokens), item) for item in rows]
    scored = [(hits, item) for hits, item in scored if hits]
    if not scored:
        return []
    scored.sort(key=lambda pair: (-pair[0], (pair[1].name or "").lower()))
    best = scored[0][0]
    return [item for hits, item in scored if hits == best]


def _vehicle_facts(item) -> dict:
    vehicle = getattr(item, "vehicle", None)
    href = _path("items.detail", item_id=item.id) or f"/items/{item.id}"
    return {
        "id": item.id,
        "name": item.name,
        "year": getattr(vehicle, "year", None) or "",
        "make": getattr(vehicle, "make", None) or "",
        "model": getattr(vehicle, "model", None) or "",
        "trim": getattr(vehicle, "trim", None) or "",
        "color": getattr(vehicle, "color", None) or "",
        "vin": getattr(vehicle, "vin", None) or "",
        "plate": getattr(vehicle, "plate", None) or "",
        "oil_needs": getattr(vehicle, "oil_needs", None) or "",
        "oil_in_it": getattr(vehicle, "oil_type", None) or "",
        "capacity": getattr(vehicle, "oil_capacity", None) or "",
        "href": href,
    }


def _speak_vehicle_facts(rows: list, text: str) -> str:
    if not rows:
        return ""
    want_vin = bool(re.search(r"\bvin\b", text or "", re.I))
    lines = []
    for item in rows:
        card = _vehicle_facts(item)
        who = " ".join(str(card[k]) for k in ("year", "make", "model", "color") if card[k]).strip()
        head = card["name"] if not who else f"{card['name']} · {who}"
        if want_vin:
            vin = card["vin"] or "no VIN saved on it"
            lines.append(f"{head} · VIN {vin} · {card['href']}")
        else:
            bits = [head]
            if card["vin"]:
                bits.append(f"VIN {card['vin']}")
            if card["plate"]:
                bits.append(card["plate"])
            if card["oil_needs"]:
                bits.append(f"needs {card['oil_needs']}")
            elif card["oil_in_it"]:
                bits.append(f"in it {card['oil_in_it']}")
            bits.append(card["href"])
            lines.append(" · ".join(bits))
    return "\n".join(lines)


_TOKEN_EXPAND = {
    "gen": ("gen", "generator", "genset"),
    "genset": ("gen", "generator", "genset"),
    "generator": ("gen", "generator", "genset"),
    "mower": ("mower", "lawnmower", "lawn"),
    "lawnmower": ("mower", "lawnmower", "lawn"),
    "tundra": ("tundra", "trundra"),
    "trundra": ("tundra", "trundra"),
}


def _machine_tokens(text: str) -> list[str]:
    return _vehicle_tokens(text)


def _machine_blob(item) -> str:
    parts = [
        getattr(item, "name", None) or "",
        getattr(item, "notes", None) or "",
        getattr(item, "category", None) or "",
        getattr(item, "item_type", None) or "",
    ]
    tool = getattr(item, "tool", None)
    if tool is not None:
        parts.extend(
            str(getattr(tool, key) or "")
            for key in (
                "type",
                "model",
                "serial_number",
                "power_source",
                "fuel_type",
                "oil_needs",
                "oil_type",
                "asset_id",
            )
        )
    return " ".join(parts).lower() + " " + _vehicle_blob(item)


def _machine_hits(item, tokens: list[str]) -> int:
    blob = _machine_blob(item)
    hits = 0
    for tok in tokens:
        alts = _TOKEN_EXPAND.get(tok, (tok,))
        if any(alt in blob for alt in alts):
            hits += 1
            continue
        if tok.isdigit() and len(tok) == 4 and tok[-2:] in blob:
            hits += 1
    return hits


def _matching_machines(text: str, types: tuple[str, ...] = ("tool", "vehicle")) -> list:
    tokens = _machine_tokens(text)
    rows = []
    for kind in types:
        for item in _find_items("", kind, limit=40):
            if all(item.id != old.id for old in rows):
                rows.append(item)
    if not rows or not tokens:
        return []
    scored = [(_machine_hits(item, tokens), item) for item in rows]
    scored = [(hits, item) for hits, item in scored if hits]
    if not scored:
        try:
            from app.utils.household import household_id
            from app.utils.search import search_household

            hits = search_household(
                household_id(),
                " ".join(tokens),
                user_id=current_user.id,
                limit=12,
                scope="all",
            )
            for item in hits.get("item_rows") or []:
                if item.item_type in types and all(item.id != old.id for old in rows):
                    scored.append((1, item))
        except Exception:
            pass
    if not scored:
        return []
    scored.sort(key=lambda pair: (-pair[0], (pair[1].name or "").lower()))
    best = scored[0][0]
    return [item for hits, item in scored if hits == best]


def _oil_fields(item) -> dict:
    host = getattr(item, "vehicle", None) or getattr(item, "tool", None)
    if host is None:
        return {}
    return {
        "needs": getattr(host, "oil_needs", None) or "",
        "in_it": getattr(host, "oil_type", None) or "",
        "capacity": getattr(host, "oil_capacity", None) or "",
        "last": str(getattr(host, "last_oil_change_date", None) or getattr(host, "last_oil_date", None) or ""),
        "next": str(getattr(host, "next_oil_due_date", None) or ""),
        "interval_miles": getattr(host, "oil_interval_miles", None) or "",
        "interval_hours": getattr(host, "oil_interval_hours", None) or "",
        "interval_months": getattr(host, "oil_interval_months", None) or "",
    }


def _item_card(item) -> dict:
    href = _path("items.detail", item_id=item.id) or f"/items/{item.id}"
    card = {
        "id": item.id,
        "name": item.name,
        "kind": item.item_type,
        "href": href,
        "barcode": getattr(item, "barcode", None) or "",
        "notes": (getattr(item, "notes", None) or "")[:500],
    }
    tool = getattr(item, "tool", None)
    if tool is not None:
        card.update(
            {
                "type": tool.type or "",
                "model": tool.model or "",
                "serial": tool.serial_number or "",
                "power": tool.power_source or "",
                "fuel": tool.fuel_type or "",
                "hours": str(tool.hours_used or ""),
            }
        )
        card.update(_oil_fields(item))
    if getattr(item, "vehicle", None) is not None:
        card.update(_vehicle_facts(item))
        card.update(_oil_fields(item))
    grocery = getattr(item, "grocery", None)
    if grocery is not None:
        from app.utils.lots import soonest
        from app.utils.scan import qty_label

        day = soonest(grocery)
        card.update(
            {
                "qty": qty_label(getattr(grocery, "quantity", None)),
                "place": grocery.default_location or "",
                "expires": day.isoformat() if day else "",
            }
        )
    return card


def _speak_card(card: dict) -> str:
    if not isinstance(card, dict):
        return str(card or "")
    name = card.get("name") or "item"
    who = " ".join(
        str(card.get(k) or "")
        for k in ("year", "make", "model", "color", "type")
        if card.get(k)
    ).strip()
    bits = [f"{name} · {who}" if who else name]
    if card.get("serial"):
        bits.append(f"serial {card['serial']}")
    if card.get("vin"):
        bits.append(f"VIN {card['vin']}")
    if card.get("plate"):
        bits.append(card["plate"])
    if card.get("power"):
        bits.append(card["power"])
    if card.get("fuel"):
        bits.append(card["fuel"])
    needs = card.get("oil_needs") or card.get("needs") or ""
    in_it = card.get("oil_in_it") or card.get("in_it") or ""
    if needs:
        bits.append(f"needs {needs}")
    elif in_it:
        bits.append(f"in it {in_it}")
    elif card.get("kind") in ("tool", "vehicle") or "needs" in card or "oil_needs" in card:
        bits.append("no oil spec saved")
    if card.get("capacity"):
        bits.append(card["capacity"])
    if card.get("expires"):
        bits.append(f"use by {card['expires']}")
    if card.get("qty"):
        bits.append(str(card["qty"]))
    if card.get("place"):
        bits.append(card["place"])
    if card.get("href"):
        bits.append(card["href"])
    return " · ".join(str(b) for b in bits if b)


def _speak_oil(item) -> str:
    card = _item_card(item)
    return _speak_card(card)


def _all_oil_say() -> str:
    lines = []
    for kind in ("vehicle", "tool"):
        for item in _find_items("", kind, limit=40):
            oil = _oil_fields(item)
            if oil.get("needs") or oil.get("in_it"):
                lines.append(_speak_oil(item))
    bottles = []
    try:
        from app.utils.household import household_id
        from app.utils.search import search_household

        hits = search_household(household_id(), "oil", user_id=current_user.id, limit=8, scope="groceries")
        for item in hits.get("item_rows") or []:
            bottles.append(_item_line(item))
    except Exception:
        pass
    if not lines and not bottles:
        return "No oil spec is saved on a vehicle or tool yet. Name one and I can look it up and add it."
    parts = []
    if lines:
        parts.append("Oil on file:\n" + "\n".join(f"· {ln}" for ln in lines))
    if bottles:
        parts.append("Oil in inventory:\n" + "\n".join(f"· {ln}" for ln in bottles))
    return "\n".join(parts)


def _oil_targets(text: str) -> list:
    raw = text or ""
    rows = _matching_machines(raw)
    if rows:
        return rows
    if re.search(r"\b(truck|trucks|car|cars|van|suv|vehicle|vehicles)\b", raw, re.I):
        return _find_items("", "vehicle", limit=8)
    if re.search(r"\b(gen|genset|generator|mower|tool|tools|equipment)\b", raw, re.I):
        tools = _find_items("", "tool", limit=12)
        if re.search(r"\b(gen|genset|generator)\b", raw, re.I):
            named = [t for t in tools if _machine_hits(t, ["gen", "gas"]) or "generat" in _machine_blob(t)]
            if named:
                return named
        return tools
    return []


def _oil_overview(text: str) -> bool:
    raw = text or ""
    if _machine_tokens(raw):
        return False
    if re.search(r"\b(truck|trucks|car|cars|van|suv|vehicle|vehicles|gen|genset|generator|mower|tool|tools)\b", raw, re.I):
        return False
    return True


def _oil_local_say(text: str) -> str | None:
    raw = (text or "").strip()
    if not re.search(r"\boil\b", raw, re.I):
        return None
    rows = _oil_targets(raw)
    if not rows:
        if _oil_overview(raw):
            return _all_oil_say()
        return None
    with_oil = [item for item in rows if _oil_fields(item).get("needs") or _oil_fields(item).get("in_it")]
    if len(rows) == 1 and with_oil:
        return _speak_oil(rows[0])
    if len(rows) == 1:
        researched = _oil_research_say(rows[0])
        if researched:
            return researched
        return None
    if with_oil and len(with_oil) == len(rows):
        return "\n".join(_speak_oil(item) for item in rows)
    if len(rows) > 1:
        names = ", ".join(r.name for r in rows[:6])
        return f"Which one? {names}"
    if _oil_overview(raw):
        return _all_oil_say()
    return None


def _oil_inspect_note(text: str) -> dict | None:
    raw = (text or "").strip()
    if not re.search(r"\boil\b", raw, re.I):
        return None
    rows = _oil_targets(raw)
    if len(rows) != 1:
        return None
    item = rows[0]
    oil = _oil_fields(item)
    if oil.get("needs") or oil.get("in_it"):
        return None
    return {
        "tool": "item_inspect",
        "result": {
            "ok": True,
            "card": _item_card(item),
            "oil_saved": False,
            "hint": "No oil spec is saved. Look up the OEM spec from year/make/model/VIN, tell them, and ask if you should oil_save it.",
        },
    }


def _stash_pending_oil(item, spec: dict) -> None:
    if not has_request_context() or not spec.get("needs"):
        return
    session[SESSION_OIL_PENDING] = {
        "item_id": item.id,
        "name": item.name,
        "needs": spec.get("needs") or "",
        "capacity": spec.get("capacity") or "",
        "interval_miles": spec.get("interval_miles") or "",
        "interval_months": spec.get("interval_months") or "",
        "interval_hours": spec.get("interval_hours") or "",
        "note": spec.get("note") or "",
    }
    session.pop(SESSION_EXPIRE_PENDING, None)


def _lookup_oem_oil(item) -> dict:
    """OEM spec from saved year/make/model/VIN plus the household AI key."""
    card = _item_card(item)
    vin = (card.get("vin") or "").strip()
    engine = ""
    if vin:
        try:
            from app.utils.vehicle_lookup import decode_vin

            decoded = decode_vin(vin)
            facts = decoded.get("facts") or {}
            engine = " ".join(
                str(facts.get(k) or "")
                for k in ("engine", "displacement_l", "cylinders", "fuel_type")
                if facts.get(k)
            ).strip()
            for key in ("year", "make", "model", "trim"):
                if not card.get(key) and facts.get(key):
                    card[key] = facts.get(key)
        except Exception:
            engine = ""
    who = " ".join(
        str(card.get(k) or "") for k in ("year", "make", "model", "color", "type") if card.get(k)
    ).strip()
    prompt = (
        "OEM engine oil for this exact machine. JSON only.\n"
        "No oil spec is saved on this site.\n"
        f"Name: {card.get('name') or ''}\n"
        f"Kind: {card.get('kind') or ''}\n"
        f"Year/make/model: {who}\n"
        f"VIN: {vin or 'none on file'}\n"
        f"Engine: {engine or 'unknown'}\n"
        f"Tool model: {card.get('model') or ''}\n"
        f"Power: {card.get('power') or ''}\n"
        "Return JSON: "
        '{"needs":"0W-20 API SN ILSAC GF-5","capacity":"6.2 qt","interval_miles":"10000",'
        '"interval_months":"12","interval_hours":null,"note":"Toyota spec for this engine"}.\n'
        "needs is viscosity plus OEM spec. Use the owner's manual / OEM recommendation. "
        "If this is a generator or tool, use that model's manual, not a truck. "
        "null for unknown fields. No markdown."
    )
    household = getattr(current_user, "household", None)
    ok, raw = complete(
        prompt,
        system="OEM oil lookup. Short JSON only. Not a chatbot.",
        max_tokens=280,
        timeout=25,
        household=household,
        household_only=True,
        job="heavy",
    )
    parsed = parse_json_object(raw) if ok else None
    spec = {}
    if isinstance(parsed, dict) and not parsed.get("error"):
        spec = {
            "needs": _trim(parsed.get("needs") or parsed.get("oil") or parsed.get("spec"), 200),
            "capacity": _trim(parsed.get("capacity") or parsed.get("oil_capacity"), 40),
            "interval_miles": _trim(parsed.get("interval_miles"), 20),
            "interval_months": _trim(parsed.get("interval_months"), 8),
            "interval_hours": _trim(parsed.get("interval_hours"), 8),
            "note": _trim(parsed.get("note"), 200),
        }
    if not spec.get("needs") and ok:
        from app.utils.oil import fields_from_text

        pulled = fields_from_text(raw or "")
        if pulled.get("needs"):
            spec = {**pulled, "note": spec.get("note") or ""}
    if spec.get("needs"):
        spec["engine"] = engine
        spec["who"] = who
        spec["vin"] = vin
        spec["href"] = card.get("href") or ""
        spec["name"] = card.get("name") or item.name
        return spec
    return {}


def _oil_research_say(item) -> str | None:
    spec = _lookup_oem_oil(item)
    if not spec.get("needs"):
        return None
    _stash_pending_oil(item, spec)
    who = spec.get("who") or item.name
    head = item.name if item.name in who else f"{item.name} · {who}".strip(" ·")
    bits = [f"{head} is on the site. No oil spec saved."]
    if spec.get("engine"):
        bits.append(f"Engine {spec['engine']}.")
    oem = f"OEM suggests {spec['needs']}"
    if spec.get("capacity"):
        oem += f", {spec['capacity']}"
    if spec.get("interval_miles"):
        oem += f", every {spec['interval_miles']} miles"
    elif spec.get("interval_hours"):
        oem += f", every {spec['interval_hours']} hours"
    if spec.get("interval_months"):
        oem += f" or {spec['interval_months']} months"
    bits.append(oem + ".")
    if spec.get("note"):
        bits.append(spec["note"])
    href = spec.get("href") or f"/items/{item.id}"
    bits.append(f"Want me to add that? {href}")
    return " ".join(bits)


def tool_oil_lookup(args: dict | None = None) -> dict:
    args = args if isinstance(args, dict) else {}
    q = _trim(args.get("q") or args.get("item") or args.get("name") or args.get("vehicle"), 200)
    item, err = _pick_named_item(q, ("vehicle", "tool"))
    if err:
        return err
    oil = _oil_fields(item)
    card = _item_card(item)
    if oil.get("needs") or oil.get("in_it"):
        return {"ok": True, "saved": True, "card": card, "oil_saved": True, "href": card.get("href") or ""}
    spec = _lookup_oem_oil(item)
    if not spec.get("needs"):
        return {
            "ok": True,
            "saved": False,
            "card": card,
            "oil_saved": False,
            "hint": "No OEM spec came back. Say the viscosity if you know it, or try again.",
            "href": card.get("href") or "",
        }
    _stash_pending_oil(item, spec)
    return {
        "ok": True,
        "saved": False,
        "card": card,
        "oil_saved": False,
        "oem": spec,
        "href": spec.get("href") or "",
        "hint": "Ask if they want this saved with oil_save.",
    }


_YES_ADD = re.compile(
    r"^\s*(?:please\s+)?(?:"
    r"(?:yes|yeah|yep|yup|ok|okay|sure)"
    r"(?:\s*,?\s*(?:please\s+)?(?:add(?:\s+it|\s+that|\s+them)?|save(?:\s+it|\s+that)?|do it|go ahead))?|"
    r"add(?:\s+it|\s+that|\s+them)?|"
    r"save(?:\s+it|\s+that)?|"
    r"do it|go ahead"
    r")\s*[.!]?\s*$",
    re.I,
)
_GENERIC_EXPIRE = re.compile(
    r"(?:add|put|apply|fill|set|give).{0,50}(?:generic|typical|usual|standard|default|shelf).{0,30}(?:expir|use[- ]?by|date)|"
    r"(?:generic|typical|usual)\s+(?:expir|use[- ]?by|dates?)",
    re.I,
)
_ITEM_WHERE = re.compile(
    r"\b(inventory|pantry|fridge|freezer|grocery|groceries|food|kitchen|garage|"
    r"tools?|truck|trucks?|vehicle|vehicles?|car|cars?|house)\b",
    re.I,
)
_NO_ADD = re.compile(r"^\s*(no|nope|cancel|never mind|don't|do not)\b", re.I)


def _apply_pending_oil() -> dict | None:
    if not has_request_context():
        return None
    pending = session.get(SESSION_OIL_PENDING)
    if not isinstance(pending, dict) or not pending.get("item_id"):
        return None
    item, err = _pick_named_item(str(pending["item_id"]), ("vehicle", "tool"))
    if err or item is None:
        session.pop(SESSION_OIL_PENDING, None)
        return {
            "ok": True,
            "say": "That vehicle or tool is gone. Name it again and I can look the oil up.",
            "did": [],
            "vault_locked": False,
        }
    if not (can("maintain") or can("edit_meta")):
        return {
            "ok": False,
            "say": "You cannot update the oil record.",
            "did": [],
            "vault_locked": False,
        }
    from app.utils.oil import save_item_oil

    save_item_oil(
        item,
        {
            "needs": pending.get("needs"),
            "capacity": pending.get("capacity"),
            "interval_miles": pending.get("interval_miles"),
            "interval_months": pending.get("interval_months"),
            "interval_hours": pending.get("interval_hours"),
        },
        clear=False,
    )
    db.session.commit()
    session.pop(SESSION_OIL_PENDING, None)
    href = _path("items.detail", item_id=item.id) or f"/items/{item.id}"
    return {
        "ok": True,
        "say": f"Saved {pending.get('needs')} on {item.name}. {href}",
        "did": ["oil"],
        "vault_locked": False,
    }


def _parse_add_where(text: str) -> dict:
    t = (text or "").lower()
    place = ""
    if re.search(r"\b(fridge|refrigerator)\b", t):
        place = "fridge"
    elif re.search(r"\bfreezer\b", t):
        place = "freezer"
    elif re.search(r"\bpantry\b", t):
        place = "pantry"
    elif re.search(r"\bkitchen\b", t):
        place = "kitchen"
    elif re.search(r"\bgarage\b", t):
        place = "garage"
    kind = None
    if re.search(r"\b(inventory|grocery|groceries|food|pantry|fridge|freezer|kitchen)\b", t):
        kind = "grocery"
    elif re.search(r"\btools?\b", t):
        kind = "tool"
    elif re.search(r"\bhouse\b", t):
        kind = "house"
    if re.search(r"\b(truck|trucks|vehicle|vehicles|car|cars|tundra|silverado|civic)\b", t):
        vehicles = _matching_machines(text, ("vehicle",))
        if vehicles:
            item = vehicles[0]
            return {
                "kind": "vehicle",
                "place": place or item.name,
                "vehicle": item.name,
                "vehicle_id": item.id,
            }
    if kind is None and place:
        kind = "grocery"
    return {"kind": kind, "place": place, "vehicle": "", "vehicle_id": None}


def _where_label(where: dict) -> str:
    kind = (where or {}).get("kind") or ""
    place = (where or {}).get("place") or ""
    vehicle = (where or {}).get("vehicle") or ""
    if kind == "tool":
        return "tools"
    if kind == "house":
        return "the house"
    if kind == "vehicle":
        return f"the {vehicle}" if vehicle else "that vehicle"
    if kind == "grocery":
        return f"inventory ({place})" if place else "inventory"
    return "inventory, tools, a vehicle, or the house"


def _stash_pending_item(payload: dict) -> None:
    if not has_request_context():
        return
    session[SESSION_ITEM_PENDING] = payload
    session.pop(SESSION_OIL_PENDING, None)


def _ask_where_to_add(name: str, *, upc: str = "", amount=1, place: str = "", where_text: str = "") -> dict:
    extra = ""
    if has_request_context():
        extra = getattr(g, "ask_message", "") or ""
    guess = _parse_add_where(" ".join(x for x in (name, place, where_text, extra) if x))
    if not guess.get("kind") and place:
        guess = {"kind": "grocery", "place": place, "vehicle": "", "vehicle_id": None}
    if guess.get("kind") != "vehicle":
        brain = {}
        try:
            from app.utils.classify import guess_item_home, usual_store_place

            household = None
            try:
                if current_user and getattr(current_user, "is_authenticated", False):
                    household = getattr(current_user, "household", None)
            except Exception:
                household = None
            brain = guess_item_home(name, household=household, extra=extra, upc=upc) or {}
            if not brain.get("place"):
                brain["place"] = usual_store_place(name) or usual_store_place(extra) or ""
        except Exception:
            from app.utils.classify import usual_store_place as _usual

            brain = {"kind": "grocery", "place": _usual(name) or _usual(extra) or ""}
        if not guess.get("kind"):
            guess["kind"] = brain.get("kind") or "grocery"
        if guess.get("kind") == "grocery" and not (guess.get("place") or "").strip():
            guess["place"] = (brain.get("place") or place or "").strip()
    if guess.get("kind") == "grocery" and guess.get("place"):
        try:
            from app.utils.places import snap_location

            household = getattr(current_user, "household", None) if current_user else None
            guess["place"] = snap_location(guess["place"], household) or guess["place"]
        except Exception:
            pass
    _stash_pending_item(
        {
            "name": name,
            "upc": upc,
            "amount": amount,
            "kind": guess.get("kind") or "",
            "place": guess.get("place") or place,
            "vehicle": guess.get("vehicle") or "",
            "vehicle_id": guess.get("vehicle_id"),
        }
    )
    if guess.get("kind") == "grocery" and guess.get("place"):
        from app.utils.ask_confirm import confirm_mode

        if confirm_mode() == "allow":
            created = _create_from_pending(guess)
            if created.get("ok"):
                return created
        return {
            "ok": False,
            "need": ["confirm"],
            "name": name,
            "guess": "grocery",
            "place": guess.get("place") or "",
            "hint": f"{name} isn’t on the site yet. I’ll put it in {guess['place']}.",
        }
    if guess.get("kind"):
        hint = (
            f"{name} isn’t on the site yet. Add it to {_where_label(guess)}? "
            "Say yes, or pick inventory, tools, a vehicle, or the house."
        )
    else:
        hint = (
            f"{name} isn’t on the site yet. Where should it go — inventory (pantry/fridge), "
            "tools, a vehicle, or the house?"
        )
    return {
        "ok": False,
        "need": ["confirm", "where"],
        "name": name,
        "choices": ["inventory", "tools", "vehicle", "house"],
        "guess": guess.get("kind") or "",
        "hint": hint,
    }


def _create_from_pending(where: dict) -> dict:
    pending = session.get(SESSION_ITEM_PENDING) if has_request_context() else None
    if not isinstance(pending, dict) or not pending.get("name"):
        return {"ok": False, "error": "Nothing waiting to add."}
    from app.routes.items import can_create_type, quick_create_item
    from app.utils.household import household_id

    name = pending.get("name") or "Item"
    upc = pending.get("upc") or ""
    amount = pending.get("amount") or 1
    kind = (where.get("kind") or pending.get("kind") or "grocery").strip().lower()
    place = where.get("place") or pending.get("place") or ""
    vehicle_id = where.get("vehicle_id") or pending.get("vehicle_id")
    vehicle_name = where.get("vehicle") or pending.get("vehicle") or ""
    hid = household_id()
    session.pop(SESSION_ITEM_PENDING, None)
    if kind == "tool":
        if not can_create_type("tool"):
            return {"ok": False, "error": "You cannot add tools."}
        item, status = quick_create_item(
            hid=hid, user_id=current_user.id, name=name, item_type="tool", barcode=upc or None
        )
        if item is None:
            return {"ok": False, "error": status or "Could not add that tool."}
        href = _path("items.detail", item_id=item.id) or f"/items/{item.id}"
        return {"ok": True, "id": item.id, "name": item.name, "did": "saved", "href": href, "where": "tools"}
    if kind == "house":
        from app.utils.ask_do import tool_part_save

        return tool_part_save({"name": name, "vehicle": "house", "serial": upc})
    if kind == "vehicle":
        if not vehicle_id:
            rows = _matching_machines(vehicle_name, ("vehicle",)) if vehicle_name else _find_items("", "vehicle", limit=8)
            if len(rows) == 1:
                vehicle_id = rows[0].id
                vehicle_name = rows[0].name
            elif rows:
                names = ", ".join(r.name for r in rows[:6])
                _stash_pending_item({**pending, "kind": "vehicle"})
                return {
                    "ok": False,
                    "need": ["where"],
                    "hint": f"Which vehicle for {name}? {names}",
                    "choices": [r.name for r in rows[:8]],
                }
            else:
                _stash_pending_item(pending)
                return {
                    "ok": False,
                    "need": ["where"],
                    "hint": f"Which vehicle should {name} go on?",
                }
        if not can_create_type("tool"):
            return {"ok": False, "error": "You cannot add equipment to a vehicle."}
        item, status = quick_create_item(
            hid=hid,
            user_id=current_user.id,
            name=name,
            item_type="tool",
            barcode=upc or None,
            linked_item_id=vehicle_id,
        )
        if item is None:
            return {"ok": False, "error": status or "Could not add that."}
        href = _path("items.detail", item_id=item.id) or f"/items/{item.id}"
        return {
            "ok": True,
            "id": item.id,
            "name": item.name,
            "did": "saved",
            "href": href,
            "where": vehicle_name or "vehicle",
        }
    if not can_create_type("grocery"):
        return {"ok": False, "error": "You cannot add inventory."}
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
    href = _path("items.detail", item_id=item.id) or f"/items/{item.id}"
    label = f"inventory ({place})" if place else "inventory"
    if status == "exists":
        return {"ok": True, "id": item.id, "name": item.name, "did": "already had it · restocked", "href": href, "where": label}
    return {"ok": True, "id": item.id, "name": item.name, "did": "saved", "href": href, "where": label}


def _speak_add_result(result: dict, name: str) -> str:
    if not result.get("ok"):
        return str(result.get("hint") or result.get("error") or "Could not add that.")
    where = result.get("where") or "the house"
    href = result.get("href") or ""
    return f"Added {result.get('name') or name} to {where}. {href}".strip()


def _apply_pending_item(text: str) -> dict | None:
    pending = session.get(SESSION_ITEM_PENDING) if has_request_context() else None
    if not isinstance(pending, dict) or not pending.get("name"):
        return None
    if _NO_ADD.match(text or ""):
        session.pop(SESSION_ITEM_PENDING, None)
        return {
            "ok": True,
            "say": f"Okay, I left {pending.get('name')} off.",
            "did": [],
            "vault_locked": False,
        }
    where = _parse_add_where(text)
    if not where.get("kind"):
        where = {
            "kind": pending.get("kind") or "grocery",
            "place": pending.get("place") or "",
            "vehicle": pending.get("vehicle") or "",
            "vehicle_id": pending.get("vehicle_id"),
        }
    result = _create_from_pending(where)
    if result.get("need"):
        return {"ok": True, "say": result.get("hint") or "Which one?", "did": [], "vault_locked": False}
    return {
        "ok": bool(result.get("ok")),
        "say": _speak_add_result(result, pending.get("name") or "it"),
        "did": ["item"] if result.get("ok") else [],
        "vault_locked": False,
    }


def _confirm_pending(text: str) -> dict | None:
    raw = (text or "").strip()
    if _GENERIC_EXPIRE.search(raw):
        result = tool_expire_guess()
        session.pop(SESSION_EXPIRE_PENDING, None)
        return {
            "ok": True,
            "say": _speak_expire_guess(result),
            "did": ["expire"] if result.get("ok") else [],
            "vault_locked": False,
        }
    if session.get(SESSION_ITEM_PENDING) and (
        _YES_ADD.match(raw) or _ITEM_WHERE.search(raw) or _NO_ADD.match(raw)
    ):
        applied = _apply_pending_item(raw)
        if applied:
            return applied
    if session.get(SESSION_REMOVE_PENDING) and (_YES_ADD.match(raw) or _NO_ADD.match(raw)):
        if _NO_ADD.match(raw):
            pending = session.pop(SESSION_REMOVE_PENDING, {}) or {}
            return {
                "ok": True,
                "say": f"Okay, I left {pending.get('name') or 'it'} in the house.",
                "did": [],
                "vault_locked": False,
            }
        pending = session.get(SESSION_REMOVE_PENDING) or {}
        item, err = _pick_named_item(str(pending.get("id") or ""), (pending.get("kind") or "grocery",))
        session.pop(SESSION_REMOVE_PENDING, None)
        if err or item is None:
            return {
                "ok": True,
                "say": "That item is already gone.",
                "did": [],
                "vault_locked": False,
            }
        result = _soft_remove_item(item)
        return {
            "ok": True,
            "say": f"Removed {result.get('name') or item.name} from the house. {result.get('href') or ''}".strip(),
            "did": ["remove"],
            "vault_locked": False,
        }
    if not _YES_ADD.match(raw):
        return None
    if session.get(SESSION_OIL_PENDING):
        return _apply_pending_oil()
    if session.get(SESSION_EXPIRE_PENDING):
        result = tool_expire_guess()
        session.pop(SESSION_EXPIRE_PENDING, None)
        return {
            "ok": True,
            "say": _speak_expire_guess(result),
            "did": ["expire"] if result.get("ok") else [],
            "vault_locked": False,
        }
    return None


def tool_vehicle_card(args: dict | None = None) -> dict:
    args = args if isinstance(args, dict) else {}
    q = _trim(args.get("q") or args.get("name") or args.get("item") or "", 200)
    rows = _matching_vehicles(q)
    if not rows:
        return {"ok": True, "q": q, "vehicles": [], "hint": "No saved vehicle matches that."}
    return {"ok": True, "q": q, "vehicles": [_vehicle_facts(item) for item in rows[:8]]}


def _stored_vehicle_say(text: str) -> str | None:
    raw = (text or "").strip()
    if not raw:
        return None
    if asked_to_list(raw, "vehicles"):
        return None
    if re.search(r"\boil\b", raw, re.I):
        return None
    if not re.search(r"\b(vin|plate)\b", raw, re.I) and "my site" not in raw.lower() and "already" not in raw.lower():
        return None
    if not _vehicle_tokens(raw) and not re.search(r"\bvin\b", raw, re.I):
        return None
    rows = _matching_vehicles(raw)
    if rows:
        return _speak_vehicle_facts(rows, raw)
    return None


def asked_to_list(text: str, kind: str | None = None) -> bool:
    """Only dump a list when they asked to see it — not “show 2 in inventory.”"""
    t = (text or "").strip().lower()
    if not t:
        return False
    if t in ("tools", "vehicles", "cars", "trucks", "basket", "inventory", "pantry", "groceries"):
        return True
    if re.search(r"\bshow in(?:to)? (?:the |my |our )?(inventory|pantry|fridge|freezer)\b", t):
        return False
    if re.search(r"\b(show|have|set|keep)\b.{0,24}\b\d", t) and re.search(r"\binventory\b", t):
        return False
    kinds = {
        "inventory": r"inventory|pantry|grocer(?:y|ies)?",
        "vehicles": r"vehicles?|cars?|trucks?|fleet",
        "tools": r"tools?",
        "basket": r"basket|shopping list",
    }
    noun = kinds.get(kind or "", r"inventory|pantry|grocer(?:y|ies)?|tools?|vehicles?|cars?|trucks?|basket")
    if re.search(rf"\b(show|list|open|display)\s+(?:me |us |my |our |the |all )?(?:the )?({noun})\b", t):
        return True
    if re.search(rf"\b(what|which)\s+({noun})\s+(do i|do we|have i|have we|i have|we have)\b", t):
        return True
    if re.search(rf"\blook(?:ing)?(?:\s+up)?\s+what\s+({noun})\b", t):
        return True
    if re.search(rf"\b({noun})\s+(do i have|i have|we have|have i|have we)\b", t):
        return True
    if re.search(rf"\bwhat(?:'s| is|s)?\s+in\s+(?:my |the |our )?({noun})\b", t):
        return True
    return False


def tool_house(args: dict | None = None) -> dict:
    args = args if isinstance(args, dict) else {}
    kind = _trim(args.get("kind") or args.get("what") or "tools", 20).lower()
    list_kind = "tools"
    if kind in ("vehicle", "vehicles", "car", "cars", "truck", "trucks"):
        list_kind = "vehicles"
    elif kind in ("basket", "list", "shopping"):
        list_kind = "basket"
    elif kind in ("grocery", "groceries", "inventory", "pantry", "food"):
        list_kind = "inventory"
    msg = ""
    if has_request_context():
        msg = str(getattr(g, "ask_message", "") or "")
    if msg and not asked_to_list(msg, list_kind):
        href = {
            "tools": "/tools/",
            "vehicles": "/vehicles/",
            "basket": "/groceries/list",
            "inventory": "/groceries/",
        }.get(list_kind, "/")
        return {
            "ok": False,
            "need": ["list_ok"],
            "kind": list_kind,
            "href": href,
            "hint": (
                f"They did not ask to see the {list_kind} list. Do not dump it. "
                "Do the work they asked, or inspect one named item."
            ),
        }
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


_TRIP_START = re.compile(
    r"\b(start|starting|begin|open)\b.{0,50}\btrip\b|\btrip\b.{0,40}\b(from|to)\b",
    re.I,
)
_TRIP_END = re.compile(
    r"\b(i['’]?m\s+home|im\s+home|home\s+with|end(?:ing)?\s+(?:the\s+)?trip|trip\s+is\s+(?:over|done)|back\s+home)\b",
    re.I,
)
_TRIP_FROM_TO = re.compile(r"from\s+([^,\n]+?)\s+to\s+([^,\n]+?)(?:\s+with|\s+at|\s*$|,)", re.I)
_TRIP_NAMED = re.compile(
    r"\b(?:in|on|for|with)\s+(?:my|the|our)\s+(.+)",
    re.I,
)
_TRIP_MILES = re.compile(
    r"(?:with|at|odometer|odo|start(?:ing)?)\s*[:=]?\s*(\d{3,7})"
    r"|(\d{3,7})\s*(?:miles|mi)\b"
    r"|(\d{3,7})\s*(?:at\s+)?start\b",
    re.I,
)


def _trip_miles_from(text: str):
    m = _TRIP_MILES.search(text or "")
    if not m:
        return None
    return m.group(1) or m.group(2) or m.group(3)


def _clean_trip_hint(raw: str) -> str:
    hint = (raw or "").strip()
    hint = re.split(r"[?!,]|\s+with\b|\s+from\b|\s+at\b|\d{3,7}", hint, maxsplit=1, flags=re.I)[0]
    return hint.strip(" .,-")[:80]


def _trip_item_hint(text: str, *, ending: bool) -> str:
    raw = text or ""
    named = _TRIP_NAMED.search(raw)
    if named:
        hint = _clean_trip_hint(named.group(1))
        if hint:
            return hint
    try:
        rows = _matching_machines(raw, ("vehicle",))
        if len(rows) == 1:
            return rows[0].name
    except Exception:
        pass
    if ending:
        return ""
    return ""


def _trip_local_say(text: str) -> str | None:
    raw = (text or "").strip()
    if not raw:
        return None
    start = bool(_TRIP_START.search(raw))
    end = bool(_TRIP_END.search(raw))
    if not start and not end:
        return None
    miles = _trip_miles_from(raw)
    if end and not start and not miles and not re.search(r"\btrip\b", raw, re.I):
        return None
    from app.utils.ask_do import tool_trip_save

    origin, dest = "", ""
    route = _TRIP_FROM_TO.search(raw)
    if route:
        origin = route.group(1).strip(" .,").title()
        dest = route.group(2).strip(" .,").title()
    action = "start" if start and not end else "end"
    args = {
        "item": _trip_item_hint(raw, ending=(action == "end")),
        "action": action,
        "reading": miles or "",
    }
    if origin:
        args["origin"] = origin
    if dest:
        args["dest"] = dest
    try:
        from app.utils.ask_do import _trip_vehicle

        item, _err = _trip_vehicle(args)
        if item is not None:
            args["item"] = item.name
    except Exception:
        pass
    from app.utils.ask_confirm import hold_writes, should_hold_tool

    if should_hold_tool("trip_save", args):
        return hold_writes([{"tool": "trip_save", "args": args}])
    result = tool_trip_save(args)
    if result.get("need") or result.get("error"):
        return str(result.get("hint") or result.get("error") or "")
    return _speak_result("trip_save", result) or None


_SORT_INV = re.compile(
    r"\b(sort|organize|organise|arrange|file)\b.{0,50}\b(inventory|inventories|pantry|grocer(?:y|ies)?|food|items|rooms?)\b"
    r"|\b(inventory|pantry|grocer(?:y|ies)?).{0,40}\b(sort|organize|organise|rooms?)\b"
    r"|\bput\b.{0,40}\b(inventory|pantry|grocer(?:y|ies)?|items|food).{0,30}\brooms?\b"
    r"|\bsort all\b",
    re.I,
)


def _sort_local_say(text: str):
    raw = (text or "").strip()
    if not raw or not _SORT_INV.search(raw):
        return None
    if re.search(r"\b(notes?|discord|dump)\b", raw, re.I) and not re.search(
        r"\b(inventory|pantry|grocer)", raw, re.I
    ):
        return None
    from app.utils.ask_do import tool_inventory_sort

    args = {"only_empty": "1"}
    if re.search(r"\b(re-?sort|again|overwrite|already have a room)\b", raw, re.I):
        args["only_empty"] = "0"
    from app.utils.ask_confirm import hold_writes, should_hold_tool

    if should_hold_tool("inventory_sort", args):
        return hold_writes([{"tool": "inventory_sort", "args": args}])
    result = tool_inventory_sort(args)
    if result.get("need") or result.get("error") and not result.get("ok"):
        return str(result.get("hint") or result.get("error") or "")
    return _speak_inventory_sort(result)


def _speak_inventory_sort(r: dict) -> str:
    if not isinstance(r, dict):
        return str(r or "")
    if r.get("error") and not r.get("moved"):
        return str(r.get("error"))
    href = r.get("href") or "/groceries/"
    moved = int(r.get("moved") or 0)
    lines = [str(x) for x in (r.get("lines") or []) if x][:16]
    if moved <= 0:
        return (r.get("hint") or "Rooms already looked fine. Nothing moved.") + f" {href}"
    head = f"Put {moved} in rooms" if r.get("used_ai") else f"Guessed rooms for {moved}"
    body = "\n".join(f"· {ln}" for ln in lines)
    return f"{head}:\n{body}\n{href}".strip()


def _expire_local_say(text: str) -> str | None:
    t = (text or "").strip().lower()
    if not t:
        return None
    if not re.search(r"expir|use[- ]?by|going bad|goes bad|about to go bad", t):
        return None
    if re.search(r"\b(add|save|create|set|put|change|delete|remove)\b", t):
        return None
    return _speak_expire(tool_expire_list({"days": 21}))


_PUT_ROOM = re.compile(
    r"\b(?:go(?:es)?|put|live|belong|keep|store)\s+"
    r"(?:them |these |those |it |this )?"
    r"(?:in(?:to)?(?:\s+the)?)\s+"
    r"(fridge|refrigerator|freezer|pantry|bathroom|garage|laundry|closet|kitchen)\b",
    re.I,
)
_SET_QTY = re.compile(
    r"\b(?:show|have|set|keep)\b.{0,48}?\b(\d{1,4})\b",
    re.I,
)


def _stock_item_name(text: str, cut_at: int | None = None) -> str:
    raw = (text or "")[: cut_at if cut_at is not None else None]
    raw = re.split(r"\b(close those|those|them|and make sure|and show)\b", raw, maxsplit=1, flags=re.I)[0]
    return raw.strip(" .,;:!?")[:120]


def _stock_local_say(text: str):
    raw = (text or "").strip()
    if not raw:
        return None
    if asked_to_list(raw):
        return None
    room_m = _PUT_ROOM.search(raw)
    qty_m = _SET_QTY.search(raw)
    if not room_m and not qty_m:
        return None
    name = _stock_item_name(raw, room_m.start() if room_m else None)
    if len(name) < 3:
        return None
    args = {"q": name, "action": "place"}
    if room_m:
        args["place"] = room_m.group(1)
    if qty_m:
        args["action"] = "set"
        args["amount"] = qty_m.group(1)
    from app.utils.ask_confirm import hold_writes, should_hold_tool

    if should_hold_tool("inventory", args):
        return hold_writes([{"tool": "inventory", "args": args}])
    result = tool_inventory(args)
    if result.get("need") or result.get("error"):
        return str(result.get("hint") or result.get("error") or "")
    return _speak_result("inventory", result) or None


def _local_house_say(text: str) -> str | None:
    t = (text or "").strip().lower()
    if not t:
        return None
    if re.search(
        r"\b(add|save|create|new|delete|remove|share|oil|note|spec|filter|tire|battery|expir|set|trip|sort|organize|organise|freezer|fridge|go in|put )\b",
        t,
    ):
        return None
    if asked_to_list(t, "tools"):
        return _speak_house(tool_house({"kind": "tools"}))
    if asked_to_list(t, "vehicles"):
        return _speak_house(tool_house({"kind": "vehicles"}))
    if asked_to_list(t, "basket"):
        return _speak_house(tool_house({"kind": "basket"}))
    if asked_to_list(t, "inventory"):
        return _speak_house(tool_house({"kind": "inventory"}))
    if re.search(r"\b(what(?:'s| is)? due|what(?:'s| is)? (?:on )?the list|show (?:me )?(?:the )?reminders?)\b", t) or t in (
        "due",
        "reminders",
    ):
        due = tool_due()
        open_rows = due.get("open") or []
        if not open_rows:
            return "Nothing due right now. /reminders/"
        return "Due:\n" + "\n".join(f"· {ln}" for ln in open_rows)
    return None


def _undated_tail(result: dict) -> str:
    try:
        n = int(result.get("undated") or 0)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        return ""
    samples = [str(x) for x in (result.get("undated_names") or []) if x][:4]
    extra = f" ({', '.join(samples)})" if samples else ""
    return (
        f"\n{n} have no use-by{extra}. "
        "Say “add generic expirations” and I’ll put typical shelf life on those."
    )


def _speak_expire(result: dict) -> str:
    rows = result.get("items") or result.get("expiring") or []
    href = result.get("href") or "/groceries/"
    tail = _undated_tail(result)
    if has_request_context() and result.get("undated"):
        session[SESSION_EXPIRE_PENDING] = True
    if not rows:
        empty = result.get("empty") or "Nothing with a use-by date in the next few weeks."
        return (empty + tail).strip() + (f"\n{href}" if href else "")
    lines = []
    for row in rows:
        if isinstance(row, dict):
            name = row.get("name") or "item"
            day = row.get("expires") or row.get("expires_on") or ""
            when = f" · {day}" if day else ""
            extra = ""
            days = row.get("days")
            if days is not None:
                try:
                    n = int(days)
                    extra = " · expired" if n < 0 else (" · today" if n == 0 else f" · {n}d")
                except (TypeError, ValueError):
                    extra = ""
            lines.append(f"· {name}{when}{extra}" + (f" · {row.get('href')}" if row.get("href") else ""))
        else:
            lines.append(f"· {row}")
    return f"Going bad soon:\n" + "\n".join(lines) + tail + (f"\n{href}" if href else "")


def _speak_result(tool: str, r: dict) -> str:
    if not isinstance(r, dict):
        return str(r or "")
    if r.get("need"):
        return str(r.get("hint") or ("Need: " + ", ".join(str(x) for x in r["need"])))
    if r.get("error"):
        return str(r["error"])
    if tool == "house" or (r.get("kind") and r.get("lines") is not None):
        return _speak_house(r)
    if tool in ("expire_list",) or r.get("expiring") is not None or r.get("undated") is not None and r.get("items") is not None:
        return _speak_expire(r)
    if tool == "expire_guess" or r.get("filled") is not None and r.get("skipped") is not None:
        return _speak_expire_guess(r)
    if tool == "inventory_sort" or r.get("did") == "sorted":
        return _speak_inventory_sort(r)
    if tool == "trip_save":
        if r.get("did") == "trip started":
            title = (r.get("title") or "").strip()
            extra = f", {title}" if title and title.lower() != "trip" else ""
            return (
                f"Trip started on {r.get('name')}{extra} "
                f"at {int(r.get('start_miles') or 0):,} miles. {r.get('href') or ''}"
            ).strip()
        if r.get("did") == "trip ended":
            return (
                f"{r.get('title') or 'Trip'}: {int(r.get('miles') or 0):,} miles. "
                f"{r.get('name')} is at {int(r.get('end_miles') or 0):,} miles. {r.get('href') or ''}"
            ).strip()
    if tool == "oil_lookup":
        oem = r.get("oem") or {}
        if oem.get("needs"):
            name = (r.get("card") or {}).get("name") or oem.get("name") or "that machine"
            return (
                f"{name} is on the site. No oil spec saved. OEM suggests {oem.get('needs')}"
                + (f", {oem['capacity']}" if oem.get("capacity") else "")
                + ". Want me to add that?"
            )
        if r.get("card"):
            return _speak_card(r["card"])
    card = r.get("card")
    if tool == "item_inspect" or card:
        if card:
            spoken = _speak_card(card)
            if r.get("oil_saved") is False and "no oil spec" not in spoken.lower():
                spoken += " · no oil spec saved"
            return spoken
        if r.get("choices"):
            return r.get("hint") or ("Which one? " + ", ".join(str(x) for x in r["choices"]))
    if r.get("vehicles"):
        return "\n".join(_speak_card(card) if isinstance(card, dict) else str(card) for card in r["vehicles"])
    if r.get("items"):
        vals = r["items"]
        if vals and isinstance(vals[0], dict):
            if vals[0].get("expires") or vals[0].get("expires_on"):
                return _speak_expire(r)
            return "\n".join(_speak_card(v) for v in vals)
        return "\n".join(str(x) for x in vals)
    if r.get("lines"):
        return _speak_house(r)
    if r.get("people"):
        return "People: " + ", ".join(
            f"{p.get('name')} ({p.get('username')}, {p.get('role')})"
            for p in r["people"]
            if isinstance(p, dict)
        )
    if r.get("entries"):
        return "Vault: " + ", ".join(
            (e.get("title") or "card") + (f" {e.get('href')}" if e.get("href") else "")
            for e in r["entries"]
            if isinstance(e, dict)
        )
    if r.get("did") in ("moved", "set", "restock", "place") or r.get("place"):
        name = r.get("name") or "That"
        loc = r.get("place") or ""
        qty = r.get("qty")
        bit = f"{name} is in {loc}" if loc else name
        if qty is not None and str(qty) != "":
            bit += f". {qty} on hand"
        href = r.get("href") or ""
        return f"{bit}. {href}".strip()
    if r.get("ok") and (r.get("href") or r.get("title") or r.get("name")):
        did = r.get("did") or "Saved"
        return f"{did} {r.get('title') or r.get('name') or ''}".strip() + (f" {r.get('href')}" if r.get("href") else "")
    return ""


def _speak_tool_notes(notes: list) -> str:
    bits = []
    for n in notes:
        r = n.get("result") or {}
        spoken = _speak_result(n.get("tool") or "", r)
        if spoken:
            bits.append(spoken)
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
    tool = getattr(item, "tool", None)
    if tool is not None:
        who = " ".join(
            str(getattr(tool, key) or "")
            for key in ("type", "model", "power_source")
            if getattr(tool, key, None)
        ).strip()
        if who:
            bits.append(who)
        if getattr(tool, "serial_number", None):
            bits.append(f"serial {tool.serial_number}")
        if getattr(tool, "oil_needs", None):
            bits.append(f"needs {tool.oil_needs}")
        elif getattr(tool, "oil_type", None):
            bits.append(f"in it {tool.oil_type}")
    vehicle = getattr(item, "vehicle", None)
    if vehicle is not None:
        who = " ".join(
            str(getattr(vehicle, key) or "")
            for key in ("year", "make", "model", "color")
            if getattr(vehicle, key, None)
        ).strip()
        if who:
            bits.append(who)
        if getattr(vehicle, "vin", None):
            bits.append(f"VIN {vehicle.vin}")
        if getattr(vehicle, "plate", None):
            bits.append(vehicle.plate)
        if getattr(vehicle, "oil_needs", None):
            bits.append(f"needs {vehicle.oil_needs}")
        elif getattr(vehicle, "oil_type", None):
            bits.append(f"in it {vehicle.oil_type}")
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


def _pick_named_item(q: str, types: tuple[str, ...] | None = None):
    needle = _trim(q, 200)
    kinds = types or ("tool", "vehicle", "grocery", "house")
    if not needle:
        return None, {"ok": False, "need": ["q"], "hint": "Which tool, vehicle, or item?"}
    if needle.isdigit():
        found = _find_items(needle, None, limit=1)
        item = found[0] if found else None
        if item is None:
            return None, {"ok": False, "error": "Nothing saved with that id."}
        if item.item_type not in kinds:
            return None, {"ok": False, "error": f"{item.name} is a {item.item_type}."}
        return item, None
    rows = _matching_machines(needle, tuple(k for k in kinds if k in ("tool", "vehicle", "house")))
    if "grocery" in kinds:
        for row in _find_items(needle, "grocery", limit=6):
            if all(row.id != old.id for old in rows):
                rows.append(row)
    if not rows:
        for kind in kinds:
            for row in _find_items(needle, kind, limit=4):
                if all(row.id != old.id for old in rows):
                    rows.append(row)
    if len(rows) == 1:
        return rows[0], None
    if len(rows) > 1:
        names = ", ".join(r.name for r in rows[:6])
        return None, {
            "ok": False,
            "need": ["q"],
            "choices": [r.name for r in rows[:8]],
            "hint": f"Which one? {names}",
        }
    return None, {"ok": False, "error": f"Nothing saved matches {needle}."}


def tool_item_inspect(args: dict | None = None) -> dict:
    args = args if isinstance(args, dict) else {}
    q = _trim(args.get("q") or args.get("name") or args.get("item") or "", 200)
    item, err = _pick_named_item(q)
    if err:
        return err
    card = _item_card(item)
    oil = _oil_fields(item)
    return {
        "ok": True,
        "card": card,
        "oil_saved": bool(oil.get("needs") or oil.get("in_it")),
        "href": card.get("href") or "",
    }


def _can_remove_item(item) -> bool:
    kind = getattr(item, "item_type", None) or ""
    if kind == "house":
        return False
    from app.routes.items import can_create_type

    return can_create_type(kind)


def _soft_remove_item(item) -> dict:
    from datetime import datetime as _dt

    from sqlalchemy.orm.attributes import flag_modified

    from app.utils.activity import record

    extra = dict(item.extra_data) if isinstance(item.extra_data, dict) else {}
    if item.barcode:
        extra["removed_barcode"] = item.barcode
        item.barcode = None
        item.extra_data = extra
        flag_modified(item, "extra_data")
    item.removed_at = _dt.utcnow()
    record(
        action="item.remove",
        summary=f"{current_user.name or current_user.username} removed {item.name}",
        target_table="items",
        target_id=item.id,
        item_id=item.id,
        old_json={"name": item.name, "item_type": item.item_type},
        reversible=True,
    )
    db.session.commit()
    href = "/tools/" if item.item_type == "tool" else "/vehicles/" if item.item_type == "vehicle" else "/groceries/"
    return {
        "ok": True,
        "id": item.id,
        "name": item.name,
        "kind": item.item_type,
        "did": "removed",
        "href": href,
    }


def _name_token_hits(item, tokens: list[str]) -> int:
    blob = (getattr(item, "name", None) or "").lower()
    extra = getattr(item, "category", None) or ""
    grocery = getattr(item, "grocery", None)
    if grocery is not None:
        extra = " ".join(str(x or "") for x in (extra, grocery.brand, grocery.size))
    blob = (blob + " " + extra).lower()
    return sum(1 for tok in tokens if tok and tok in blob)


def _pick_for_remove(q: str):
    needle = _trim(q, 200)
    if not needle:
        return None, {"ok": False, "need": ["q"], "hint": "Which item should I take out?"}
    raw = needle.lower()
    wants_vehicle = bool(re.search(r"\b(truck|trucks|car|cars|van|suv|vehicle|vehicles)\b", raw))
    wants_tool = bool(re.search(r"\b(tool|tools|drill|mower|gen|generator|saw)\b", raw))
    foodish = bool(
        re.search(
            r"\b(protein|bar|bars|milk|cereal|snack|chip|chips|food|grocery|groceries|"
            r"pantry|bread|egg|eggs|yogurt|juice|soda|candy)\b",
            raw,
        )
    )
    if wants_vehicle and not foodish:
        order = ("vehicle", "tool", "grocery")
    elif wants_tool and not foodish:
        order = ("tool", "grocery", "vehicle")
    else:
        order = ("grocery", "tool", "vehicle")
    tokens = [t for t in _machine_tokens(needle) if t not in ("delete", "remove", "removed")]
    hits = []
    for kind in order:
        found = _find_items(needle, kind, limit=8)
        if not found and tokens:
            scored = []
            for item in _find_items("", kind, limit=40):
                n = _name_token_hits(item, tokens)
                need = min(2, len(tokens)) if len(tokens) > 1 else 1
                if n >= need:
                    scored.append((n, item))
            scored.sort(key=lambda pair: (-pair[0], (pair[1].name or "").lower()))
            found = [item for _, item in scored[:6]]
        if kind == "vehicle" and not wants_vehicle:
            found = [
                item
                for item in found
                if tokens and _name_token_hits(item, tokens) >= min(2, len(tokens) or 1)
            ]
        for item in found:
            if all(item.id != old.id for old in hits):
                hits.append(item)
        if hits:
            break
    if len(hits) == 1:
        return hits[0], None
    if len(hits) > 1:
        names = ", ".join(f"{r.name} ({r.item_type})" for r in hits[:6])
        return None, {
            "ok": False,
            "need": ["q"],
            "choices": [r.name for r in hits[:8]],
            "hint": f"Which one? {names}",
        }
    return None, {"ok": False, "error": f"Nothing saved matches {needle}."}


def tool_item_remove(args: dict | None = None) -> dict:
    args = args if isinstance(args, dict) else {}
    q = _trim(args.get("q") or args.get("name") or args.get("item") or "", 200)
    item, err = _pick_for_remove(q)
    if err:
        return err
    if not _can_remove_item(item):
        return {
            "ok": False,
            "denied": True,
            "error": f"You cannot remove {item.name}. That stays with someone who can edit it.",
        }
    from app.utils.ask_confirm import write_needs_confirm

    if write_needs_confirm("item_remove", args):
        if has_request_context():
            session[SESSION_REMOVE_PENDING] = {
                "id": item.id,
                "name": item.name,
                "kind": item.item_type,
            }
        kind = {"grocery": "inventory", "tool": "tools", "vehicle": "vehicles"}.get(item.item_type, item.item_type)
        href = _path("items.detail", item_id=item.id) or f"/items/{item.id}"
        return {
            "ok": False,
            "need": ["confirm"],
            "id": item.id,
            "name": item.name,
            "kind": item.item_type,
            "href": href,
            "hint": (
                f"Remove {item.name} from {kind}? Say yes. "
                "That is the only thing I will take out."
            ),
        }
    return _soft_remove_item(item)


def _expire_day(raw) -> date | None:
    from app.utils.lots import parse_day

    day = parse_day(raw)
    if day:
        return day
    text = _trim(raw, 40).lower()
    today = date.today()
    if text in ("today",):
        return today
    if text in ("tomorrow",):
        return today + timedelta(days=1)
    match = re.match(r"in\s+(\d{1,3})\s+days?", text)
    if match:
        return today + timedelta(days=int(match.group(1)))
    return None


def tool_expire_list(args: dict | None = None) -> dict:
    args = args if isinstance(args, dict) else {}
    try:
        days = int(args.get("days") or args.get("within") or 21)
    except (TypeError, ValueError):
        days = 21
    days = max(1, min(days, 365))
    today = date.today()
    cutoff = today + timedelta(days=days)
    from app.utils.lots import soonest
    from app.utils.scan import qty_label

    out = []
    undated = []
    for item in _find_items("", "grocery", limit=200):
        grocery = getattr(item, "grocery", None)
        if grocery is None:
            continue
        day = soonest(grocery)
        href = _path("items.detail", item_id=item.id) or f"/items/{item.id}"
        if day is None:
            undated.append(item.name)
            continue
        if day > cutoff:
            continue
        out.append(
            {
                "id": item.id,
                "name": item.name,
                "expires": day.isoformat(),
                "days": (day - today).days,
                "qty": qty_label(getattr(grocery, "quantity", None)),
                "place": grocery.default_location or "",
                "href": href,
            }
        )
    out.sort(key=lambda row: (row["expires"], (row["name"] or "").lower()))
    n_undated = len(undated)
    empty = f"Nothing with a use-by date in the next {days} days."
    if n_undated and not out:
        empty = f"None of the {n_undated} food rows have a use-by yet."
    return {
        "ok": True,
        "days": days,
        "items": out[:40],
        "undated": n_undated,
        "undated_names": undated[:8],
        "href": "/groceries/",
        "empty": empty,
    }


def tool_expire_save(args: dict | None = None) -> dict:
    args = args if isinstance(args, dict) else {}
    if not (can("edit_grocery") or can("scan") or can("edit_meta")):
        return {"ok": False, "error": "You cannot set a use-by date."}
    q = _trim(args.get("q") or args.get("name") or args.get("item") or "", 200)
    item, err = _pick_named_item(q, ("grocery",))
    if err:
        return err
    grocery = getattr(item, "grocery", None)
    if grocery is None:
        return {"ok": False, "error": f"{item.name} is not inventory."}
    day = _expire_day(args.get("date") or args.get("expires") or args.get("expires_on") or args.get("due") or "")
    if day is None:
        return {
            "ok": False,
            "need": ["date"],
            "hint": "What date? Use YYYY-MM-DD, today, tomorrow, or in 3 days.",
        }
    from app.utils.lots import apply_partial, summary_line

    qty = args.get("amount") or args.get("qty") or args.get("quantity") or 1
    place = _trim(args.get("place") or args.get("location"), 80)
    apply_partial(
        grocery,
        [{"qty": qty, "expires_on": day.isoformat(), "place": place}],
    )
    if place and not (grocery.default_location or "").strip():
        grocery.default_location = place
    db.session.commit()
    href = _path("items.detail", item_id=item.id) or f"/items/{item.id}"
    return {
        "ok": True,
        "id": item.id,
        "name": item.name,
        "expires": day.isoformat(),
        "line": summary_line(grocery) or day.isoformat(),
        "href": href,
        "did": "dated",
    }


def _speak_expire_guess(result: dict) -> str:
    if not result.get("ok"):
        return str(result.get("error") or "Could not put typical dates on those.")
    filled = result.get("filled") or []
    skipped = int(result.get("skipped") or 0)
    still = int(result.get("undated") or 0)
    n = len(filled)
    if n == 0 and still:
        return f"Could not guess a date for {still} rows (paper goods and the like stay blank). /groceries/"
    lines = [f"Put typical use-by dates on {n} item{'s' if n != 1 else ''}."]
    for row in filled[:8]:
        if isinstance(row, dict):
            lines.append(f"· {row.get('name')} · {row.get('expires')}")
        else:
            lines.append(f"· {row}")
    if n > 8:
        lines.append(f"· and {n - 8} more")
    if skipped:
        lines.append(f"{skipped} already had a date.")
    if still:
        lines.append(f"{still} still have no date.")
    lines.append(result.get("href") or "/groceries/")
    return "\n".join(lines)


def tool_expire_guess(args: dict | None = None) -> dict:
    args = args if isinstance(args, dict) else {}
    if not (can("edit_grocery") or can("scan") or can("edit_meta")):
        return {"ok": False, "error": "You cannot set a use-by date."}
    from app.utils.lots import soonest
    from app.utils.shelf_life import apply_shelf_life

    household = getattr(current_user, "household", None)
    filled = []
    skipped = 0
    still = []
    for item in _find_items("", "grocery", limit=200):
        grocery = getattr(item, "grocery", None)
        if grocery is None:
            continue
        had = soonest(grocery)
        if had is not None:
            skipped += 1
            continue
        try:
            apply_shelf_life(item, grocery, force=False, household=household)
        except Exception:
            still.append(item.name)
            continue
        day = soonest(grocery)
        if day is None:
            still.append(item.name)
            continue
        href = _path("items.detail", item_id=item.id) or f"/items/{item.id}"
        filled.append({"id": item.id, "name": item.name, "expires": day.isoformat(), "href": href})
    db.session.commit()
    return {
        "ok": True,
        "filled": filled,
        "skipped": skipped,
        "undated": len(still),
        "undated_names": still[:8],
        "href": "/groceries/",
        "did": "dated",
    }


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
    rows = _find_items(q, "grocery") if q else []
    if upc and not rows:
        from app.builddb.table_items import Item

        hit = Item.query.filter_by(household_id=hid, barcode=upc).filter(Item.removed_at.is_(None)).first()
        if hit is not None:
            rows = [hit]
    if not rows:
        name = q or "Item"
        where_text = _trim(args.get("where") or args.get("on") or place, 80)
        return _ask_where_to_add(name, upc=upc, amount=amount, place=place, where_text=where_text)
    if action == "create":
        action = "restock"
    item = rows[0]
    g = item.grocery
    if g is None:
        return {"ok": False, "error": f"{item.name} is not an inventory row."}
    if not place and not (g.default_location or "").strip():
        try:
            from app.utils.classify import guess_item_home

            household = getattr(current_user, "household", None) if current_user else None
            place = guess_item_home(item.name, household=household).get("place") or ""
        except Exception:
            place = ""
    if place:
        try:
            from app.utils.places import snap_location

            household = getattr(current_user, "household", None) if current_user else None
            place = snap_location(place, household) or place
        except Exception:
            pass
        if place and (g.default_location or "").strip().lower() != place.lower():
            g.default_location = place
    if action == "place":
        db.session.commit()
        href = _path("items.detail", item_id=item.id) or f"/items/{item.id}"
        return {
            "ok": True,
            "id": item.id,
            "name": item.name,
            "qty": qty_label(g.quantity),
            "place": g.default_location or place,
            "did": "moved",
            "href": href,
        }
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
        "place": g.default_location or place or "",
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
        if key == "vehicle_card":
            return tool_vehicle_card(args)
        if key == "item_inspect":
            return tool_item_inspect(args)
        if key == "item_remove":
            return tool_item_remove(args)
        if key == "due":
            return tool_due()
        if key == "expire_list":
            return tool_expire_list(args)
        if key == "expire_save":
            return tool_expire_save(args)
        if key == "expire_guess":
            return tool_expire_guess(args)
        if key == "oil_lookup":
            return tool_oil_lookup(args)
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
        if key == "member_password":
            from app.utils.ask_do import tool_member_password

            return tool_member_password(args)
        if key == "member_remove":
            from app.utils.ask_do import tool_member_remove

            return tool_member_remove(args)
        if key == "part_save":
            from app.utils.ask_do import tool_part_save

            return tool_part_save(args)
        if key == "log_save":
            from app.utils.ask_do import tool_log_save

            return tool_log_save(args)
        if key == "trip_save":
            from app.utils.ask_do import tool_trip_save

            return tool_trip_save(args)
        if key == "legal_save":
            from app.utils.ask_do import tool_legal_save

            return tool_legal_save(args)
        if key == "oil_save":
            from app.utils.ask_do import tool_oil_save

            return tool_oil_save(args)
        if key == "oil_lookup":
            return tool_oil_lookup(args)
        if key == "expire_guess":
            return tool_expire_guess(args)
        if key == "inventory_sort":
            from app.utils.ask_do import tool_inventory_sort

            return tool_inventory_sort(args)
    except Exception as exc:
        return {"ok": False, "error": f"Could not do that: {exc}"}
    return {"ok": False, "error": f"Unknown tool {name}."}


_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S | re.I)


def _json_objects(text: str) -> list[dict]:
    raw = (text or "").strip()
    fenced = _JSON_FENCE.search(raw)
    if fenced:
        raw = fenced.group(1).strip()
    decoder = json.JSONDecoder()
    out = []
    i = 0
    while i < len(raw):
        start = raw.find("{", i)
        if start < 0:
            break
        try:
            obj, end = decoder.raw_decode(raw, start)
        except Exception:
            i = start + 1
            continue
        if isinstance(obj, dict):
            out.append(obj)
        i = end
        if len(out) >= 8:
            break
    return out


def _looks_like_json(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    if raw.startswith("```"):
        return True
    if raw.startswith("{") and raw.endswith("}"):
        return True
    return bool(_json_objects(raw)) and raw.lstrip().startswith("{")


def _plain_say(text: str, tool_notes: list | None = None, _depth: int = 0) -> str:
    raw = (text or "").strip()
    if not raw or _depth > 3:
        return ""
    objs = _json_objects(raw)
    if objs:
        for obj in objs:
            tool = (obj.get("tool") or "").strip().lower()
            if tool in TOOLS:
                spoken = _speak_tool_notes(tool_notes or [{"tool": tool, "result": obj}])
                if spoken:
                    return spoken[:4000]
        for obj in reversed(objs):
            if "say" in obj:
                inner = _trim(obj.get("say"), 4000)
                if inner and not _looks_like_json(inner):
                    return inner
                if inner and inner != raw:
                    return _plain_say(inner, tool_notes, _depth + 1)
        spoken = _speak_result("", objs[-1]) or _speak_tool_notes(tool_notes or [])
        if spoken:
            return spoken[:4000]
        return ""
    if _looks_like_json(raw):
        return (_speak_tool_notes(tool_notes or []) or "")[:4000]
    return raw[:4000]


def _parse_turn(text: str) -> dict:
    objs = _json_objects(text or "")
    if not objs:
        parsed = parse_json_object(text or "")
        objs = [parsed] if isinstance(parsed, dict) else []
    for obj in objs:
        tool = (obj.get("tool") or "").strip().lower()
        if tool in TOOLS:
            args = obj.get("args") if isinstance(obj.get("args"), dict) else {}
            if not args:
                args = {k: v for k, v in obj.items() if k not in ("tool", "say")}
            return {"kind": "tool", "tool": tool, "args": args}
    for obj in reversed(objs):
        if "say" in obj:
            return {"kind": "say", "text": _plain_say(str(obj.get("say") or ""), None)}
        spoken = _speak_result("", obj)
        if spoken:
            return {"kind": "say", "text": spoken}
    raw = (text or "").strip()
    return {"kind": "say", "text": _plain_say(raw) if raw else ""}


def _prompt_for(history: list, message: str, tool_notes: list) -> str:
    bits = []
    for row in history[-16:]:
        role = "You" if row.get("role") == "assistant" else "Them"
        bits.append(f"{role}: {_trim(row.get('text'), 800)}")
    bits.append(f"Them: {_trim(message, MSG_CAP)}")
    for note in tool_notes:
        bits.append("Tool result JSON:\n" + json.dumps(note, ensure_ascii=False)[:3500])
    bits.append(
        "Reply with one JSON object only. If you are done, {\"say\":\"spoken English, no JSON inside\"}. "
        "Do not paste tool results. Look things up on this site; do not ask them to."
    )
    return "\n\n".join(bits)


PHOTO_TOOLS = ("place", "part_save", "tool_save", "vehicle_save", "inventory", "note_save", "legal_save")
PHOTO_ASK = (
    "Look at this photo. Read any barcode, serial, VIN, model, or part number. "
    "If there is no code, identify the tool, part, or item and put it in the right place."
)


def _saved_vehicle_brief() -> str:
    try:
        rows = _find_items("", "vehicle", limit=20)
    except Exception:
        return ""
    if not rows:
        return ""
    lines = [_speak_vehicle_facts([item], "vin") for item in rows]
    return (
        "Vehicles already saved on this site. Use this list. Do not ask for a VIN, year, or name that is already here.\n"
        + "\n".join(lines)
    )


def _system_now(has_photo: bool) -> str:
    from app.utils.ask_do import PHOTO_RULES, actor_lines
    from app.utils.ask_rooms import room_system_line

    extra = actor_lines()
    extra += "\n\n" + room_system_line(_room())
    extra += "\nSlash /help, /vehicles, /inventory, /tools, /basket, /due, /oil list this house with no extra lookup. Do not invent those lists when they typed a slash — the site already answered."
    brief = _saved_vehicle_brief()
    if brief:
        extra += "\n\n" + brief
    if has_photo:
        extra += "\n\n" + PHOTO_RULES
    return SYSTEM + "\n\n" + extra


def _with_issued_login(say: str, tool_notes: list) -> str:
    text = say or ""
    for note in tool_notes:
        if note.get("tool") not in ("member_add", "member_password"):
            continue
        result = note.get("result") or {}
        password = result.get("password") or ""
        username = result.get("username") or ""
        if not result.get("ok") or not password or password in text:
            continue
        text = text.rstrip() + f"\nUsername {username}. Password {password}. They sign in with the household handle."
    return text


def run_ask(
    message: str,
    *,
    household,
    image_bytes: bytes | None = None,
    image_mime: str | None = None,
    room: str | None = None,
) -> dict:
    from app.utils.ask_photo import (
        attach_pending,
        clear_ask_photo,
        load_ask_photo,
        photo_was_attached,
        stash_ask_photo,
    )

    _set_room(room)
    text = _trim(message, MSG_CAP)
    if has_request_context():
        g.ask_message = text
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
    from app.utils.ask_rooms import slash_reply

    slash = None if has_photo else slash_reply(text, _room())
    if slash:
        history = _history()
        history.append({"role": "user", "text": text})
        history.append({"role": "assistant", "text": slash})
        _save_history(history)
        return {"ok": True, "say": slash, "did": [], "vault_locked": False, "room": _room()}
    if not _rate_ok():
        return {"ok": False, "error": "Give Ask a minute. Too many questions just now."}
    from app.utils.ask_confirm import handle_reply, hold_writes, should_hold_tool

    gated = None if has_photo else handle_reply(text)
    if gated:
        history = _history()
        history.append({"role": "user", "text": text})
        history.append({"role": "assistant", "text": gated.get("say") or ""})
        _save_history(history)
        return gated
    confirmed = None if has_photo else _confirm_pending(text)
    if confirmed:
        history = _history()
        history.append({"role": "user", "text": text})
        history.append({"role": "assistant", "text": confirmed.get("say") or ""})
        _save_history(history)
        return confirmed
    remembered = None if has_photo else _remember_reply(text)
    if remembered:
        history = _history()
        history.append({"role": "user", "text": text})
        history.append({"role": "assistant", "text": remembered.get("say") or ""})
        _save_history(history)
        return remembered
    oil_say = None if has_photo else _oil_local_say(text)
    if oil_say:
        history = _history()
        history.append({"role": "user", "text": text})
        history.append({"role": "assistant", "text": oil_say})
        _save_history(history)
        return {"ok": True, "say": oil_say, "did": [], "vault_locked": False}
    stored = None if has_photo else _stored_vehicle_say(text)
    if stored:
        history = _history()
        history.append({"role": "user", "text": text})
        history.append({"role": "assistant", "text": stored})
        _save_history(history)
        return {"ok": True, "say": stored, "did": [], "vault_locked": False}
    trip_say = None if has_photo else _trip_local_say(text)
    if trip_say:
        payload = (
            trip_say
            if isinstance(trip_say, dict)
            else {"ok": True, "say": trip_say, "did": [], "vault_locked": False}
        )
        history = _history()
        history.append({"role": "user", "text": text})
        history.append({"role": "assistant", "text": payload.get("say") or ""})
        _save_history(history)
        return payload
    sort_say = None if has_photo else _sort_local_say(text)
    if sort_say:
        payload = (
            sort_say
            if isinstance(sort_say, dict)
            else {"ok": True, "say": sort_say, "did": [], "vault_locked": False}
        )
        history = _history()
        history.append({"role": "user", "text": text})
        history.append({"role": "assistant", "text": payload.get("say") or ""})
        _save_history(history)
        return payload
    expire_say = None if has_photo else _expire_local_say(text)
    if expire_say:
        history = _history()
        history.append({"role": "user", "text": text})
        history.append({"role": "assistant", "text": expire_say})
        _save_history(history)
        return {"ok": True, "say": expire_say, "did": [], "vault_locked": False}
    stock_say = None if has_photo else _stock_local_say(text)
    if stock_say:
        payload = (
            stock_say
            if isinstance(stock_say, dict)
            else {"ok": True, "say": stock_say, "did": [], "vault_locked": False}
        )
        history = _history()
        history.append({"role": "user", "text": text})
        history.append({"role": "assistant", "text": payload.get("say") or ""})
        _save_history(history)
        return payload
    local = None if has_photo else _local_house_say(text)
    if local:
        history = _history()
        history.append({"role": "user", "text": text})
        history.append({"role": "assistant", "text": local})
        _save_history(history)
        return {"ok": True, "say": local, "did": [], "vault_locked": False}
    history = _history()
    tool_notes = []
    oil_note = None if has_photo else _oil_inspect_note(text)
    if oil_note:
        tool_notes.append(oil_note)
    did = []
    queued = []
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
            job="heavy" if has_photo else "everyday",
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
            if should_hold_tool(turn["tool"], turn.get("args"), has_photo=has_photo):
                queued.append({"tool": turn["tool"], "args": turn.get("args") or {}})
                tool_notes.append(
                    {
                        "tool": turn["tool"],
                        "result": {"ok": True, "queued": True, "hint": "Waiting for you to allow this."},
                    }
                )
                continue
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
            need = result.get("need") or []
            if need == ["confirm"] and result.get("hint"):
                last_say = str(result.get("hint"))
                break
            continue
        last_say = _plain_say(turn.get("text") or "", tool_notes)
        if not last_say and tool_notes:
            last_say = _speak_tool_notes(tool_notes)
        break
    if queued:
        held = hold_writes(queued)
        last_say = held.get("say") or last_say
        last_say = _with_issued_login(last_say, tool_notes)
        history.append({"role": "user", "text": text})
        history.append({"role": "assistant", "text": last_say})
        _save_history(history)
        held["say"] = last_say
        return held
    if not last_say:
        last_say = _speak_tool_notes(tool_notes) or _oil_local_say(text) or _expire_local_say(text) or _local_house_say(text)
    last_say = _plain_say(last_say or "", tool_notes)
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
