"""Ask actions that the rest of Family OS already knows how to do.

Every write checks the same permission the page would. Missing fields come back
as need so the chat can ask, instead of inventing a username or a barcode.
"""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask_login import current_user

from app.builddb.builddb import db
from app.utils.permissions import can, role_of

PHOTO_RULES = """A photo is attached. Read every printed code exactly (UPC, EAN, QR, VIN, serial, model, part number, brand). Do not invent a code that is not visible.
Then call place with what you saw. A tool or part with no barcode or serial still gets identified (brand, model, type, and which system it belongs on) and place files it.
A ticket, citation, notice, or court paper is legal_save, not inventory.
If you cannot tell what it is, say so and ask. One photo at a time.
If the photo is from an earlier message and they changed the subject, ignore it."""

JOBS = (
    {
        "id": "add_person",
        "perm": "members",
        "title": "Add a person",
        "tool": "member_add",
        "need": ["name", "username"],
        "optional": ["role", "email", "password"],
        "how": (
            "Name, and a username that starts with a letter (then letters, numbers, underscore). "
            "Role is member, admin, or child — default member. Email is optional. "
            "Leave the password blank and one is made and shown once. "
            "They sign in with the household handle plus that username. "
            "Chat cannot make someone a leader."
        ),
    },
    {
        "id": "change_role",
        "perm": "members",
        "title": "Change someone's role",
        "tool": "member_role",
        "need": ["username", "role"],
        "optional": [],
        "how": "Username of someone else in this house, and role member, admin, or child. You cannot change your own role here.",
    },
    {
        "id": "list_people",
        "perm": None,
        "title": "List people",
        "tool": "member_list",
        "need": [],
        "optional": [],
        "how": "Who is in this household, their username and role.",
    },
    {
        "id": "save_tool",
        "perm": "maintain",
        "title": "Save a tool",
        "tool": "tool_save",
        "need": ["name"],
        "optional": ["type", "model", "serial", "barcode", "notes"],
        "how": "A name is enough. Add model, serial, or barcode when the photo or the person gave one.",
    },
    {
        "id": "save_vehicle",
        "perm": "maintain",
        "title": "Save a vehicle",
        "tool": "vehicle_save",
        "need": ["vin or plate or name"],
        "optional": ["make", "model", "year"],
        "how": "VIN, plate, or a name. A VIN or plate is looked up.",
    },
    {
        "id": "save_part",
        "perm": "maintain",
        "title": "Put a part on a vehicle or the house",
        "tool": "part_save",
        "need": ["name"],
        "optional": ["vehicle", "system", "slot", "brand", "model", "serial", "part_number", "spec"],
        "how": "Name the part. Say which vehicle, or house for the home. If they have one vehicle it is used. System and slot are guessed from the name (brake pads, oil filter, fridge).",
    },
    {
        "id": "save_grocery",
        "perm": "edit_grocery",
        "title": "Add or change inventory",
        "tool": "inventory",
        "need": ["name"],
        "optional": ["upc", "amount", "place", "action"],
        "how": "action is restock, used, set, need, or create. A barcode is looked up before a new row is made.",
    },
    {
        "id": "basket",
        "perm": ("scan", "edit_grocery"),
        "title": "Shopping basket",
        "tool": "basket_add",
        "need": ["names"],
        "optional": ["store"],
        "how": "Names to buy. Store is optional (Sam's, Costco).",
    },
    {
        "id": "reminder",
        "perm": "maintain",
        "title": "Reminder or bill",
        "tool": "reminder_save",
        "need": ["title"],
        "optional": ["type", "due", "every"],
        "how": "Title. type bill, oil_change, filter, or custom. every 30d, monthly, yearly.",
    },
    {
        "id": "note",
        "perm": None,
        "title": "Note",
        "tool": "note_save",
        "need": ["title"],
        "optional": ["body", "share"],
        "how": "Title and optional body. share personal or household.",
    },
    {
        "id": "vault",
        "perm": "vault",
        "title": "Password vault",
        "tool": "vault_save",
        "need": ["title"],
        "optional": ["login", "secret", "url", "kind"],
        "how": "Needs the vault unlocked for this login. Ask for the Family OS password if it is locked. Do not invent a password.",
    },
    {
        "id": "log",
        "perm": ("scan", "maintain", "edit_meta", "photo"),
        "title": "Log miles, hours, a fill-up, a repair, or a code",
        "tool": "log_save",
        "need": ["item"],
        "optional": ["kind", "reading", "gallons", "cost", "notes", "title", "happened"],
        "how": "Name the vehicle, tool, or the house. kind is miles, hours, fillup, repair, note, or code.",
    },
    {
        "id": "legal",
        "perm": "legal",
        "title": "Citation, ticket, or notice",
        "tool": "legal_save",
        "need": ["title"],
        "optional": ["kind", "agency", "case_number", "due", "amount", "body"],
        "how": "What the paper is. kind citation, notice, warning, ticket, court, letter, or other.",
    },
    {
        "id": "place",
        "perm": ("maintain", "edit_grocery", "edit_meta", "photo", "legal"),
        "title": "File a photo or a described item",
        "tool": "place",
        "need": ["what", "name"],
        "optional": ["barcode", "serial", "vin", "model", "brand", "part_number", "vehicle"],
        "how": "what is tool, part, grocery, vehicle, house, note, or legal. Codes that are actually printed get looked up. No code: identify the object and file it on tools, the matching vehicle system, the house, or inventory.",
    },
)

PAGE_ONLY = (
    {
        "id": "appearance",
        "perm": None,
        "title": "Look and calendar",
        "href": "/appearance/",
        "how": "Open Look. Chat does not change the theme.",
    },
    {
        "id": "household_settings",
        "perm": "settings",
        "title": "Household mail, AI key, places",
        "href": "/members/",
        "how": "Open Household. Chat does not change the AI key, mail server, or delete the house.",
    },
)


def _trim(value, cap: int) -> str:
    return ("" if value is None else str(value)).strip()[:cap]


def _allowed(perm) -> bool:
    if perm is None:
        return True
    if isinstance(perm, (tuple, list, set)):
        return any(can(p) for p in perm)
    return can(perm)


def _denied(what: str) -> dict:
    return {
        "ok": False,
        "denied": True,
        "error": f"You cannot {what}. That stays with someone who already has permission for it.",
    }


def actor_lines() -> str:
    role = role_of() or "member"
    yes = []
    no = []
    for job in list(JOBS) + list(PAGE_ONLY):
        label = job["title"]
        if job in PAGE_ONLY:
            label += " (page)"
        (yes if _allowed(job["perm"]) else no).append(label)
    return (
        f"Signed-in role: {role}. Do only the yes list. If they ask for something on the no list, say so and do not call the tool.\n"
        "Yes: " + "; ".join(yes) + ".\n"
        "No: " + ("; ".join(no) or "none") + ".\n"
        "When a tool result has need, ask for those fields in plain language. Never invent usernames, passwords, serials, barcodes, or VINs.\n"
        "Chat cannot delete the household, change the AI key, send a password reset, or make a leader. Point them at /members/ for those.\n"
        "Call guide with an action id (add_person, save_part, legal, …) when you are unsure what to ask next."
    )


def tool_guide(args: dict | None = None) -> dict:
    args = args if isinstance(args, dict) else {}
    action = _trim(args.get("action") or args.get("job") or args.get("id"), 40).lower()
    catalog = list(JOBS) + list(PAGE_ONLY)
    if not action:
        return {
            "ok": True,
            "can": [j["title"] for j in catalog if _allowed(j["perm"])],
            "cannot": [j["title"] for j in catalog if not _allowed(j["perm"])],
        }
    job = next((j for j in catalog if j["id"] == action or j.get("tool") == action), None)
    if job is None:
        return {
            "ok": False,
            "error": "No job by that name.",
            "actions": [j["id"] for j in catalog],
        }
    return {
        "ok": True,
        "action": job["id"],
        "allowed": _allowed(job["perm"]),
        "title": job["title"],
        "tool": job.get("tool") or "",
        "need": job.get("need") or [],
        "optional": job.get("optional") or [],
        "how": job["how"],
        "href": job.get("href") or "",
    }


def tool_member_list(_args: dict | None = None) -> dict:
    from app.builddb.table_users import User
    from app.utils.household import household_id

    rows = (
        User.query.filter_by(household_id=household_id(), is_active=True)
        .order_by(User.name.asc())
        .all()
    )
    people = [
        {
            "id": u.id,
            "name": u.name,
            "username": u.username,
            "role": u.role,
            "leader": bool(u.is_leader),
            "email": u.email or "",
        }
        for u in rows
    ]
    return {"ok": True, "people": people, "href": "/members/"}


def tool_member_add(args: dict | None = None) -> dict:
    args = args if isinstance(args, dict) else {}
    if not can("members"):
        return _denied("add a person")
    from app.builddb.table_households import Household
    from app.builddb.table_users import ROLES, User
    from app.utils.household import household_id
    from app.utils.household_mail import random_login_password
    from app.utils.identity import norm_username, username_taken, valid_username

    name = _trim(args.get("name") or args.get("person_name"), 150)
    username = norm_username(args.get("username") or "")
    if not name:
        return {
            "ok": False,
            "need": ["name", "username"],
            "hint": "Who is this? I need their name, then a username that starts with a letter.",
            "roles": list(ROLES),
        }
    if not username or not valid_username(username):
        suggestion = norm_username(name)
        hint = "Need a username that starts with a letter, then letters, numbers, or underscore."
        if valid_username(suggestion) and not username_taken(household_id(), suggestion):
            hint += f" {suggestion} is free if you want that."
        return {"ok": False, "need": ["username"], "hint": hint, "roles": list(ROLES)}
    hid = household_id()
    if username_taken(hid, username):
        return {"ok": False, "error": "Someone in this household already uses that username."}
    role = _trim(args.get("role"), 20).lower() or "member"
    if role == "kid":
        role = "child"
    if role in ("parent", "adult"):
        role = "member"
    if role not in ROLES:
        return {
            "ok": False,
            "need": ["role"],
            "hint": "Role has to be member, admin, or child.",
            "roles": list(ROLES),
        }
    email = _trim(args.get("email"), 120).lower() or None
    if email and "@" not in email:
        return {"ok": False, "need": ["email"], "hint": "That email does not look right. Leave it off if they have none."}
    if email and User.query.filter(User.email == email).first():
        return {"ok": False, "error": "That email is already used."}
    password = _trim(args.get("password"), 80)
    generated = False
    if not password:
        password = random_login_password()
        generated = True
    if len(password) < 8:
        return {
            "ok": False,
            "need": ["password"],
            "hint": "Password needs at least 8 characters, or leave it blank and one will be made.",
        }
    household = Household.query.get(hid)
    user = User(
        household_id=hid,
        username=username,
        name=name,
        email=email,
        role=role,
        is_leader=False,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    mailed = False
    if email:
        try:
            from flask import url_for

            from app.utils.household_mail import added_person_email_body
            from app.utils.mail import send_mail

            body = added_person_email_body(
                household=household,
                login_url=url_for("auth.login", _external=True),
                username=username,
                password=password,
                person_name=name,
                calendar_label="",
            )
            mailed, _msg = send_mail(
                email,
                f"You're on {household.name} — Family OS",
                body,
                household=household,
            )
        except Exception:
            mailed = False
    return {
        "ok": True,
        "id": user.id,
        "name": name,
        "username": username,
        "role": role,
        "email": email or "",
        "password": password,
        "generated_password": generated,
        "emailed": mailed,
        "href": "/members/",
        "did": "added",
        "hint": "Tell them the username and password once so they can sign in. They use the household handle plus this username.",
    }


def tool_member_role(args: dict | None = None) -> dict:
    args = args if isinstance(args, dict) else {}
    if not can("members"):
        return _denied("change someone's role")
    from app.builddb.table_users import ROLES, User
    from app.utils.household import household_id
    from app.utils.identity import norm_username

    hid = household_id()
    role = _trim(args.get("role"), 20).lower()
    if role == "kid":
        role = "child"
    if role and role not in ROLES:
        return {"ok": False, "need": ["role"], "hint": "Role has to be member, admin, or child.", "roles": list(ROLES)}
    if not role:
        return {"ok": False, "need": ["role"], "hint": "Which role: member, admin, or child?", "roles": list(ROLES)}
    user = None
    raw_id = args.get("id") or args.get("user_id")
    if raw_id and str(raw_id).isdigit():
        user = User.query.filter_by(id=int(raw_id), household_id=hid).first()
    username = norm_username(args.get("username") or args.get("name") or "")
    if user is None and username:
        user = User.query.filter_by(household_id=hid, username=username).first()
    if user is None:
        return {"ok": False, "need": ["username"], "hint": "Who? Use their username from member_list."}
    if user.id == current_user.id:
        return {"ok": False, "error": "You cannot change your own role here. Another leader can."}
    if role == "child" and user.is_leader:
        from app.utils.leaders import leader_count

        if leader_count(hid) <= 1:
            return {"ok": False, "error": "Promote another leader before making this person a child."}
        user.is_leader = False
    user.role = role
    db.session.commit()
    return {
        "ok": True,
        "id": user.id,
        "name": user.name,
        "username": user.username,
        "role": role,
        "href": "/members/",
        "did": "role",
    }


def _vehicles():
    from app.utils.ask import _find_items

    return _find_items("", "vehicle", limit=20)


def _pick_host(args: dict):
    """Vehicle or the house. Returns (item, error_dict)."""
    from app.builddb.table_items import Item
    from app.utils.ask import _find_items
    from app.utils.household import household_id
    from app.utils.house_systems import ensure_house_item

    raw = args.get("vehicle") or args.get("vehicle_id") or args.get("on") or args.get("host") or ""
    text = _trim(raw, 200)
    hid = household_id()
    if str(text).isdigit():
        item = (
            Item.query.filter_by(id=int(text), household_id=hid)
            .filter(Item.removed_at.is_(None))
            .first()
        )
        if item is not None and item.item_type in ("vehicle", "house"):
            return item, None
        return None, {"ok": False, "error": "That is not a vehicle or the house in this household."}
    if text.lower() in ("house", "the house", "home", "household"):
        item, _created = ensure_house_item(hid, current_user.id)
        db.session.commit()
        return item, None
    if text:
        rows = _find_items(text, "vehicle", limit=5)
        if len(rows) == 1:
            return rows[0], None
        if len(rows) > 1:
            return None, {
                "ok": False,
                "need": ["vehicle"],
                "choices": [r.name for r in rows],
                "hint": "Which vehicle? " + ", ".join(r.name for r in rows),
            }
        return None, {"ok": False, "error": f"No vehicle named {text}."}
    rows = _vehicles()
    if len(rows) == 1:
        return rows[0], None
    if not rows:
        return None, {
            "ok": False,
            "need": ["vehicle"],
            "hint": "No vehicle saved yet. Name one to add, or say house if this belongs on the house.",
        }
    return None, {
        "ok": False,
        "need": ["vehicle"],
        "choices": [r.name for r in rows],
        "hint": "Which vehicle should this go on? " + ", ".join(r.name for r in rows),
    }


def tool_part_save(args: dict | None = None) -> dict:
    args = args if isinstance(args, dict) else {}
    if not (can("maintain") or can("edit_meta")):
        return _denied("add a part")
    from app.utils.house_systems import HOUSE_SLOTS, guess_house_slot, install_house_part
    from app.utils.vehicle_systems import guess_slot, install_part, slot_label, system_label

    name = _trim(args.get("name"), 200)
    if not name:
        return {"ok": False, "need": ["name"], "hint": "What part is it?"}
    host, err = _pick_host(args)
    if err:
        return err
    brand = _trim(args.get("brand"), 120)
    model = _trim(args.get("model"), 120)
    serial = _trim(args.get("serial") or args.get("serial_number") or args.get("sn"), 120)
    part_number = _trim(args.get("part_number") or args.get("number"), 80)
    spec = _trim(args.get("spec") or args.get("size"), 160)
    notes = _trim(args.get("notes"), 2000)
    status = _trim(args.get("status") or "installed", 20).lower()
    if host.item_type == "house":
        system, slot = guess_house_slot(name, _trim(args.get("type") or args.get("kind"), 80))
        if _trim(args.get("system"), 40):
            system = _trim(args.get("system"), 40).lower()
        if _trim(args.get("slot"), 40):
            slot = _trim(args.get("slot"), 40).lower()
        row = install_house_part(
            hid=host.household_id,
            vehicle_item_id=host.id,
            user_id=current_user.id,
            system=system,
            slot=slot,
            name=name,
            brand=brand or None,
            spec=spec or None,
            part_number=part_number or None,
            model=model or None,
            serial_number=serial or None,
            status=status,
            notes=notes or None,
            replace_current=False,
            catalog_slots=HOUSE_SLOTS,
        )
    else:
        system, slot = guess_slot(None, name=name)
        if _trim(args.get("system"), 40):
            system = _trim(args.get("system"), 40).lower()
        if _trim(args.get("slot"), 40):
            slot = _trim(args.get("slot"), 40).lower()
        row = install_part(
            hid=host.household_id,
            vehicle_item_id=host.id,
            user_id=current_user.id,
            system=system,
            slot=slot,
            name=name,
            brand=brand or None,
            spec=spec or None,
            part_number=part_number or None,
            model=model or None,
            serial_number=serial or None,
            status=status,
            notes=notes or None,
            replace_current=status == "installed",
        )
    db.session.commit()
    from app.utils.ask import _path

    href = _path("items.detail", item_id=host.id) or f"/items/{host.id}"
    if host.item_type == "house":
        from app.utils.house_systems import house_system_label

        where = f"{house_system_label(row.system)} · {slot_label(row.system, row.slot, HOUSE_SLOTS)}"
    else:
        where = f"{system_label(row.system)} · {slot_label(row.system, row.slot)}"
    return {
        "ok": True,
        "id": host.id,
        "part_id": row.id,
        "name": row.name,
        "on": host.name,
        "where": where,
        "serial": serial,
        "href": href + "?tab=systems",
        "did": "saved",
    }


def _digits(raw: str) -> str:
    return re.sub(r"\D", "", raw or "")


def _existing_barcode(hid: int, barcode: str):
    from app.builddb.table_items import Item

    if not barcode:
        return None
    return (
        Item.query.filter_by(household_id=hid, barcode=barcode)
        .filter(Item.removed_at.is_(None))
        .first()
    )


def tool_place(args: dict | None = None) -> dict:
    """File what a photo or a sentence described into the spot the app already uses."""
    args = args if isinstance(args, dict) else {}
    from app.utils.ask import tool_inventory, tool_note_save, tool_tool_save, tool_vehicle_save
    from app.utils.household import household_id

    what = _trim(args.get("what") or args.get("kind") or args.get("type"), 40).lower()
    aliases = {
        "tools": "tool",
        "drill": "tool",
        "equipment": "tool",
        "parts": "part",
        "auto": "part",
        "car": "vehicle",
        "truck": "vehicle",
        "food": "grocery",
        "pantry": "grocery",
        "inventory": "grocery",
        "ticket": "legal",
        "citation": "legal",
        "notice": "legal",
        "home": "house",
        "appliance": "house",
    }
    what = aliases.get(what, what)
    name = _trim(args.get("name") or args.get("title"), 200)
    brand = _trim(args.get("brand"), 120)
    model = _trim(args.get("model"), 120)
    serial = _trim(args.get("serial") or args.get("serial_number") or args.get("sn"), 120)
    part_number = _trim(args.get("part_number") or args.get("number"), 80)
    spec = _trim(args.get("spec") or args.get("size"), 160)
    notes = _trim(args.get("notes") or args.get("body"), 2000)
    vin = _trim(args.get("vin"), 32).upper()
    code = _trim(args.get("barcode") or args.get("upc") or args.get("code"), 48)
    digits = _digits(code)
    hid = household_id()

    if what == "legal":
        return tool_legal_save(
            {
                "title": name,
                "kind": args.get("legal_kind") or args.get("paper") or "other",
                "agency": args.get("agency"),
                "body": notes,
                "due": args.get("due"),
                "amount": args.get("amount"),
            }
        )
    if what == "note":
        return tool_note_save({"title": name, "body": notes or spec, "share": args.get("share") or "household"})
    if what == "vehicle" or (vin and len(vin) >= 11):
        if not (can("maintain") or can("edit_meta")):
            return _denied("add a vehicle")
        return tool_vehicle_save(
            {
                "vin": vin,
                "plate": args.get("plate"),
                "name": name,
                "make": brand,
                "model": model,
                "year": args.get("year"),
            }
        )

    looked = {}
    if 8 <= len(digits) <= 14:
        existing = _existing_barcode(hid, digits) or _existing_barcode(hid, code)
        if existing is not None:
            from app.utils.ask import _path

            return {
                "ok": True,
                "id": existing.id,
                "name": existing.name,
                "did": "already in the house",
                "href": _path("items.detail", item_id=existing.id),
            }
        try:
            from app.utils.barcode_lookup import lookup_product

            looked = lookup_product(digits) or {}
        except Exception:
            looked = {}
        if looked.get("ok"):
            if not name:
                name = _trim(looked.get("name"), 200)
            if not brand:
                brand = _trim(looked.get("brand"), 120)
            if not spec:
                spec = _trim(looked.get("size") or looked.get("quantity"), 160)
            catalog_kind = (looked.get("kind") or "").strip().lower()
            if not what or what in ("unknown", "item"):
                if catalog_kind in ("tool", "mower", "equipment"):
                    what = "tool"
                elif catalog_kind in ("car_battery", "motor_oil", "filter", "auto_part"):
                    what = "part"
                elif catalog_kind == "vehicle":
                    what = "vehicle"
                else:
                    what = "grocery"

    display = name
    if brand and brand.lower() not in display.lower():
        display = f"{brand} {display}".strip()
    if not display:
        display = model
    blob = " ".join(p for p in (name, brand, model, spec, part_number, notes) if p)

    if not what and blob:
        from app.utils.house_systems import guess_house_slot
        from app.utils.vehicle_systems import guess_slot

        hsys, _hslot = guess_house_slot(blob, "")
        vsys, _vslot = guess_slot(None, name=blob)
        if hsys != "other":
            what = "house"
        elif vsys != "other":
            what = "part"
        elif serial or model:
            what = "tool"

    if what == "house":
        filed = dict(args)
        filed["vehicle"] = args.get("vehicle") or "house"
        filed["name"] = display or name
        return tool_part_save(filed)

    if what == "part":
        if not (can("maintain") or can("edit_meta")):
            return _denied("add a part")
        catalog_kind = (looked.get("kind") or "").strip().lower()
        if catalog_kind in ("motor_oil", "filter", "car_battery", "auto_part") and 8 <= len(digits) <= 14:
            host, err = _pick_host(args)
            if err:
                return err
            if not (can("edit_grocery") or can("edit_meta")):
                filed = dict(args)
                filed["name"] = name or display
                return tool_part_save(filed)
            from app.routes.items import quick_create_item
            from app.utils.ask import _path

            item, status = quick_create_item(
                hid=hid,
                user_id=current_user.id,
                name=display or name or "Part",
                item_type="grocery",
                barcode=digits,
                linked_item_id=host.id,
                kind=catalog_kind,
                kind_label=looked.get("kind_label") or catalog_kind,
                location=_trim(args.get("place") or looked.get("location_hint"), 80) or None,
                quantity=args.get("amount") or 1,
                action="restock",
            )
            if item is None:
                return {"ok": False, "error": status or "Could not file that part."}
            return {
                "ok": True,
                "id": item.id,
                "name": item.name,
                "on": host.name,
                "did": "saved" if status == "ok" else status,
                "href": _path("items.detail", item_id=host.id),
            }
        filed = dict(args)
        filed["name"] = name or display
        if serial:
            filed["serial"] = serial
        if part_number:
            filed["part_number"] = part_number
        if spec:
            filed["spec"] = spec
        if brand:
            filed["brand"] = brand
        if model:
            filed["model"] = model
        return tool_part_save(filed)

    if what == "grocery":
        if not (can("edit_grocery") or can("edit_meta")):
            return _denied("add inventory")
        return tool_inventory(
            {
                "q": display or name,
                "action": "create",
                "upc": digits if 8 <= len(digits) <= 14 else "",
                "amount": args.get("amount") or 1,
                "place": args.get("place") or looked.get("location_hint") or "",
            }
        )

    if what == "tool" or serial:
        if not (can("maintain") or can("edit_meta")):
            return _denied("add a tool")
        return tool_tool_save(
            {
                "name": display or name,
                "type": args.get("type") or args.get("tool_type"),
                "model": model,
                "serial": serial,
                "barcode": digits if 8 <= len(digits) <= 14 else "",
                "notes": notes,
            }
        )

    return {
        "ok": False,
        "need": ["what", "name"],
        "hint": "What is it — a tool, a car part, something in the house, groceries, or a paper notice? A name helps me file it.",
    }


def tool_log_save(args: dict | None = None) -> dict:
    args = args if isinstance(args, dict) else {}
    if not (can("scan") or can("maintain") or can("edit_meta") or can("photo")):
        return _denied("add a log")
    from app.builddb.table_item_logs import LOG_KINDS
    from app.utils.ask import _find_items, _path
    from app.utils.item_log import add_item_log

    q = _trim(args.get("item") or args.get("q") or args.get("name") or args.get("vehicle"), 200)
    if not q:
        return {"ok": False, "need": ["item"], "hint": "Which vehicle, tool, or the house?"}
    item = None
    if q.isdigit():
        found = _find_items(q, None, limit=1)
        item = found[0] if found else None
    else:
        for kind in ("vehicle", "tool", "house"):
            found = _find_items(q, kind, limit=3)
            if len(found) == 1:
                item = found[0]
                break
            if len(found) > 1:
                return {
                    "ok": False,
                    "need": ["item"],
                    "choices": [r.name for r in found],
                    "hint": "Which one? " + ", ".join(r.name for r in found),
                }
    if item is None:
        return {"ok": False, "error": f"Nothing saved matches {q}."}
    if item.item_type not in ("vehicle", "tool", "house"):
        return {"ok": False, "error": f"{item.name} does not keep a log."}
    kind = _trim(args.get("kind") or "note", 20).lower()
    if kind in ("mileage", "mile", "odometer"):
        kind = "miles"
    if kind == "hour":
        kind = "hours"
    if kind in ("gas", "fuel", "fill"):
        kind = "fillup"
    if kind in ("dtc", "error"):
        kind = "code"
    if kind not in LOG_KINDS:
        kind = "note"
    if kind == "miles" and item.item_type != "vehicle":
        kind = "hours" if item.item_type == "tool" else "note"
    if kind == "hours" and item.item_type != "tool":
        kind = "miles" if item.item_type == "vehicle" else "note"
    happened = None
    raw_day = _trim(args.get("happened") or args.get("date"), 32)
    if raw_day:
        try:
            happened = datetime.strptime(raw_day[:10], "%Y-%m-%d").date()
        except ValueError:
            happened = None
    row = add_item_log(
        item,
        kind=kind,
        user_id=current_user.id,
        reading=args.get("reading") or args.get("mileage") or args.get("hours"),
        gallons=args.get("gallons"),
        cost=args.get("cost"),
        notes=args.get("notes"),
        title=args.get("title") or args.get("code"),
        happened_on=happened,
    )
    db.session.commit()
    return {
        "ok": True,
        "id": item.id,
        "log_id": row.id,
        "name": item.name,
        "kind": kind,
        "href": _path("items.detail", item_id=item.id) or f"/items/{item.id}",
        "did": "logged",
    }


def _parse_day(raw: str):
    text = _trim(raw, 32)
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_amount(raw):
    s = _trim(raw, 20).replace("$", "").replace(",", "")
    if not s:
        return None
    try:
        d = Decimal(s)
    except (InvalidOperation, ValueError):
        return None
    if d < 0 or d > Decimal("99999999.99"):
        return None
    return d.quantize(Decimal("0.01"))


def tool_legal_save(args: dict | None = None) -> dict:
    args = args if isinstance(args, dict) else {}
    if not can("legal"):
        return _denied("save a legal record")
    from app.builddb.table_legal_records import KINDS, STATUSES, LegalRecord
    from app.utils.household import household_id

    title = _trim(args.get("title") or args.get("name"), 500)
    if not title:
        return {
            "ok": False,
            "need": ["title"],
            "hint": "What is the paper — parking ticket, code notice, a letter? I need a title before I file it.",
        }
    kind = _trim(args.get("kind") or "other", 20).lower()
    if kind not in KINDS:
        kind = "other"
    status = _trim(args.get("status") or "open", 20).lower()
    if status not in STATUSES:
        status = "open"
    row = LegalRecord(
        household_id=household_id(),
        created_by=current_user.id,
        title=title,
        kind=kind,
        status=status,
        agency=_trim(args.get("agency"), 400) or None,
        case_number=_trim(args.get("case_number") or args.get("number"), 120) or None,
        location=_trim(args.get("location"), 400) or None,
        issued_on=_parse_day(args.get("issued") or args.get("issued_on") or ""),
        due_on=_parse_day(args.get("due") or args.get("due_on") or ""),
        amount=_parse_amount(args.get("amount")),
        body=_trim(args.get("body") or args.get("notes"), 8000) or None,
    )
    db.session.add(row)
    db.session.commit()
    return {
        "ok": True,
        "id": row.id,
        "title": title,
        "kind": kind,
        "href": f"/legal/{row.id}",
        "did": "saved",
    }
