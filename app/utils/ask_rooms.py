"""Ask rooms and slash commands.

Each room keeps its own transcript so vehicle talk does not mix with
inventory. Slash commands list what is already on this site with no model.
"""
from __future__ import annotations

ROOMS = (
    "house",
    "vehicles",
    "inventory",
    "tools",
    "basket",
    "due",
    "vault",
    "people",
    "notes",
    "reminders",
)

ROOM_META = {
    "house": {
        "title": "House",
        "hint": "Anything in this house. Type /help for the list of rooms.",
        "placeholder": "What oil does the gas gen need? What’s about to expire?",
    },
    "vehicles": {
        "title": "Vehicles",
        "hint": "This thread is only vehicles — oil, VIN, parts, trips, the log.",
        "placeholder": "Start a trip in the blue tundra from Odessa to Lubbock with 81200 miles",
    },
    "inventory": {
        "title": "Inventory",
        "hint": "This thread is food and stock — counts, use-by dates, restock.",
        "placeholder": "What’s about to expire? Set milk to expire Friday.",
    },
    "tools": {
        "title": "Tools",
        "hint": "This thread is tools and generators — add, remove, oil, inspect.",
        "placeholder": "Find my gas gen and tell me what oil it needs.",
    },
    "basket": {
        "title": "Basket",
        "hint": "This thread is the shopping list.",
        "placeholder": "Add coffee creamer and paper towels from Sam’s.",
    },
    "due": {
        "title": "Due",
        "hint": "This thread is bills, oil changes, and food going bad.",
        "placeholder": "What’s due? What’s about to expire?",
    },
}

ROOM_META = dict(
    ROOM_META,
    **{
        "vault": {
            "title": "Vault",
            "hint": "Local-only lookups for saved vault cards. Unlock on the vault page first; add and edit cards there.",
            "placeholder": "What’s my Netflix login?",
        },
        "people": {
            "title": "People",
            "hint": "This thread is people in the house — add, change details, roles, passwords.",
            "placeholder": "Add Sam as a member. Change Riley’s email.",
        },
        "notes": {
            "title": "Notes",
            "hint": "This thread is notes — save, update, find, or delete them.",
            "placeholder": "Save a note: spare key is in the kitchen drawer.",
        },
        "reminders": {
            "title": "Reminders",
            "hint": "This thread is reminders — add, list, or mark them done.",
            "placeholder": "Add a reminder for the water bill on the 1st. What reminders are open?",
        },
    }
)

ROOM_ALIASES = {
    "house": "house",
    "home": "house",
    "all": "house",
    "vehicles": "vehicles",
    "vehicle": "vehicles",
    "car": "vehicles",
    "cars": "vehicles",
    "truck": "vehicles",
    "trucks": "vehicles",
    "garage": "vehicles",
    "inventory": "inventory",
    "grocery": "inventory",
    "groceries": "inventory",
    "pantry": "inventory",
    "food": "inventory",
    "tools": "tools",
    "tool": "tools",
    "gen": "tools",
    "generator": "tools",
    "equipment": "tools",
    "basket": "basket",
    "list": "basket",
    "shopping": "basket",
    "due": "due",
    "reminders": "reminders",
    "reminder": "reminders",
    "bills": "due",
    "expire": "due",
    "expires": "due",
    "vault": "vault",
    "passwords": "vault",
    "login": "vault",
    "logins": "vault",
    "people": "people",
    "person": "people",
    "family": "people",
    "member": "people",
    "members": "people",
    "notes": "notes",
    "note": "notes",
}

_ROOM_RULES_BASE = {
    "house": "This is the house thread. Prefer find and item_inspect. Point them at /ask/vehicles or /ask/inventory when the talk is only that area.",
    "vehicles": "This thread is vehicles only. Inspect trucks and cars here, start and end trips, log miles. Do not dump inventory, the basket, or tools unless they ask.",
    "inventory": "This thread is inventory only. Counts, use-by dates, restock, and the pantry. Do not dump the vehicle list.",
    "tools": "This thread is tools and generators. Inspect, add, remove, and oil_save here. Do not dump the pantry.",
    "basket": "This thread is the shopping basket. Add names, match scans, list what is on it.",
    "due": "This thread is due dates: bills, oil changes, reminders, and food going bad. Use expire_list and due.",
}

ROOM_RULES = dict(
    _ROOM_RULES_BASE,
    **{
        "vault": "This thread is local-only. Vault card lookup is handled by the app, never by an AI provider. Unlock on /vault/ first. Add or edit cards on the vault page.",
        "people": "This thread is people: member_add, member_list, member_role, member_password, member_remove, and person_update for name/email/phone changes.",
        "notes": "This thread is notes: note_save to add or update, find to locate, note_delete to remove. Household notes show to everyone.",
        "reminders": "This thread is reminders: reminder_save to add, reminder_list to show open ones, reminder_done to mark one done, due for the combined view.",
    }
)


def normalize_room(value: str | None) -> str:
    key = (value or "").strip().lower().strip("/")
    if "/" in key:
        key = key.rsplit("/", 1)[-1]
    key = ROOM_ALIASES.get(key, key)
    return key if key in ROOM_META else "house"


def room_meta(room: str | None = None) -> dict:
    key = normalize_room(room)
    meta = dict(ROOM_META[key])
    meta["id"] = key
    meta["href"] = "/ask/" if key == "house" else f"/ask/{key}"
    return meta


def rooms_public() -> list[dict]:
    return [room_meta(key) for key in ROOMS]


def room_from_path(path: str | None) -> str:
    p = (path or "").split("?", 1)[0]
    if p.startswith("/ask/help"):
        return "house"
    if p.startswith("/ask/") and len(p) > 5:
        return normalize_room(p[5:].split("/", 1)[0])
    if p.rstrip("/") == "/ask":
        return "house"
    if p.startswith("/vehicles"):
        return "vehicles"
    if p.startswith("/tools"):
        return "tools"
    if p.startswith("/groceries/list"):
        return "basket"
    if p.startswith("/groceries"):
        return "inventory"
    if p.startswith("/reminders"):
        return "due"
    return "house"


def help_text(room: str | None = None) -> str:
    here = room_meta(room)
    agent = "Ask"
    try:
        from flask_login import current_user

        from app.utils.ask import ask_identity

        if getattr(current_user, "is_authenticated", False):
            agent = ask_identity(getattr(current_user, "household", None)).get("name") or "Ask"
    except Exception:
        agent = "Ask"
    return (
        f"{agent} looks this house up and does the work: tools, vehicles, inventory, oil, "
        "use-by dates, notes, basket, bills, reminders, people, and the vault "
        "(the vault still needs this login’s password). Local saved-data reads and supported edits work without AI; online research, photos, and open-ended chat need a household AI key.\n\n"
        "Slash commands list what is already saved — no wait for the model:\n"
        "/help — this list\n"
        "/vehicles — trucks and cars on the site\n"
        "/inventory — food and stock\n"
        "/tools — tools and generators\n"
        "/basket — the shopping list\n"
        "/due — reminders, oil changes, and food going bad\n"
        "/oil — oil specs saved on machines\n"
        "/reminders — open reminders\n"
        "/notes — saved notes\n"
        "/vault — what is in the vault (unlock first)\n"
        "/people — who is in this house\n"
        "/allow and /confirm — switch run-free and ask-first\n\n"
        "Things to say:\n"
        "“what rear diff oil does my tundra take” — specs from the built-in OEM guide (works with no AI key), research online when the guide does not know\n"
        "“log an oil change on the tundra at 81,200 with 5W-30” — writes the log, then asks about the reminder\n"
        "“add a reminder for the water bill on the 1st” · “mark the water bill done”\n"
        "“put coffee creamer on the basket from Sam’s” · “take paper towels off the basket”\n"
        "“add Sam as a member” · “change Riley’s email to …” · “set Sam to admin”\n"
        "“save a note: spare key is in the kitchen drawer” · “delete the grill cover note”\n"
        "“what’s my Netflix login?” (vault must be unlocked; chat never sends secrets to AI or saves them in its transcript)\n"
        "“search online for …” — looks it up on the web and cites the source\n\n"
        "Rooms keep threads apart so messages do not mix:\n"
        + "\n".join(
            f"/ask/{key} — {ROOM_META[key]['title']}" for key in ROOMS if key != "house"
        )
        + "\n\n"
        "Trips: “start a trip in my blue tundra with 81200 miles from Odessa to Lubbock” "
        "then “I’m home with 81650 miles.” That writes the day on the truck’s Log tab and updates miles.\n\n"
        "Writes show a plan first. Allow, don’t, “always allow” (simple work runs free), or “always ask.” "
        "/allow and /confirm switch that too.\n\n"
        "Sort inventory: “sort the inventory” files food into Fridge, Pantry, and the other rooms. It does not dump the list.\n\n"
        f"You are in {here['title']}. {here['hint']}"
    )


def _speak_member_list(result: dict) -> str:
    people = result.get("people") or []
    if not people:
        return "No people saved yet. /members/"
    return "People:\n" + "\n".join(f"· {p}" for p in people) + "\n/members/"


def _speak_vault_list(result: dict) -> str:
    entries = result.get("entries") or []
    if not entries:
        return "Vault is empty or locked. Unlock it on /vault/ first. Never paste your login password in chat."
    return "Vault:\n" + "\n".join(f"· {e}" for e in entries)


def slash_name(text: str) -> str | None:
    raw = (text or "").strip()
    if not raw.startswith("/"):
        return None
    cmd = raw.split()[0].lstrip("/").lower()
    return cmd or None


def local_list(kind: str) -> str:
    from app.utils.ask import (
        _all_oil_say,
        _speak_expire,
        _speak_house,
        tool_due,
        tool_expire_list,
        tool_house,
    )

    key = normalize_room(kind)
    if kind in ("oil", "oils"):
        return _all_oil_say()
    if key == "vehicles":
        return _speak_house(tool_house({"kind": "vehicles"}))
    if key == "inventory":
        stock = _speak_house(tool_house({"kind": "inventory"}))
        going = _speak_expire(tool_expire_list({"days": 21}))
        return stock + "\n\n" + going
    if key == "tools":
        return _speak_house(tool_house({"kind": "tools"}))
    if key == "basket":
        return _speak_house(tool_house({"kind": "basket"}))
    if key == "due":
        due = tool_due()
        open_rows = due.get("open") or []
        head = (
            "Nothing due right now. /reminders/"
            if not open_rows
            else "Due:\n" + "\n".join(f"· {ln}" for ln in open_rows)
        )
        going = _speak_expire(tool_expire_list({"days": 21}))
        return head + "\n\n" + going
    if key == "reminders":
        from app.utils.ask import tool_reminder_list

        rows = (tool_reminder_list({}) or {}).get("lines") or []
        if not rows:
            return "No open reminders. Say “add a reminder for …” to add one."
        return "Open reminders:\n" + "\n".join(f"· {ln}" for ln in rows) + "\n/reminders/"
    if key == "notes":
        try:
            from app.builddb.table_notes import Note
            from app.utils.household import scoped

            rows = (
                scoped(Note)
                .order_by(Note.id.desc())
                .limit(20)
                .all()
            )
        except Exception:
            rows = []
        if not rows:
            return "No notes saved. Say “save a note: …” to add one."
        return "Notes:\n" + "\n".join(f"· {n.title or 'note'} · /notes/" for n in rows) + "\n/notes/"
    if key == "people":
        from app.utils.ask import tool_member_list

        return _speak_member_list(tool_member_list({}))
    if key == "vault":
        from app.utils.ask import tool_vault_list

        body = _speak_vault_list(tool_vault_list(""))
        return body + "\n/vault/"
    return help_text(key)


def slash_reply(text: str, room: str | None = None) -> str | None:
    cmd = slash_name(text)
    if not cmd:
        return None
    here = normalize_room(room)
    if cmd in ("help", "?"):
        return help_text(here)
    if cmd == "ask" or cmd.startswith("ask/"):
        rest = cmd.split("/", 1)[1] if "/" in cmd else ""
        if rest:
            dest = normalize_room(rest)
            body = local_list(dest)
            href = "/ask/" if dest == "house" else f"/ask/{dest}"
            if dest != here:
                body += (
                    f"\n\nOpen {href} to talk there so it stays out of this thread."
                )
            return body
        return help_text(here)
    if cmd in ("oil", "oils"):
        return local_list("oil")
    if cmd in ("allow", "free"):
        from app.utils.ask_confirm import set_mode

        return set_mode("allow").get("say") or ""
    if cmd in ("confirm", "ask-first", "askfirst"):
        from app.utils.ask_confirm import set_mode

        return set_mode("ask").get("say") or ""
    dest = ROOM_ALIASES.get(cmd)
    if dest is None:
        return f"No command named /{cmd}. Try /help."
    body = local_list(dest)
    if dest != here:
        href = "/ask/" if dest == "house" else f"/ask/{dest}"
        body += (
            f"\n\nThis is a snapshot. Talk about {ROOM_META[dest]['title'].lower()} at {href} "
            "so it stays out of this thread."
        )
    return body


def room_system_line(room: str | None = None) -> str:
    key = normalize_room(room)
    return ROOM_RULES.get(key) or ROOM_RULES["house"]
