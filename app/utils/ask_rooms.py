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
    "reminders": "due",
    "reminder": "due",
    "bills": "due",
    "expire": "due",
    "expires": "due",
}

ROOM_RULES = {
    "house": "This is the house thread. Prefer find and item_inspect. Point them at /ask/vehicles or /ask/inventory when the talk is only that area.",
    "vehicles": "This thread is vehicles only. Inspect trucks and cars here, start and end trips, log miles. Do not dump inventory, the basket, or tools unless they ask.",
    "inventory": "This thread is inventory only. Counts, use-by dates, restock, and the pantry. Do not dump the vehicle list.",
    "tools": "This thread is tools and generators. Inspect, add, remove, and oil_save here. Do not dump the pantry.",
    "basket": "This thread is the shopping basket. Add names, match scans, list what is on it.",
    "due": "This thread is due dates: bills, oil changes, reminders, and food going bad. Use expire_list and due.",
}


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
    return (
        "Ask looks this house up and does the work: tools, vehicles, inventory, oil, "
        "use-by dates, notes, basket, bills. Vault still needs this login’s password.\n\n"
        "Slash commands list what is already saved — no wait for the model:\n"
        "/help\n"
        "/vehicles\n"
        "/inventory\n"
        "/tools\n"
        "/basket\n"
        "/due\n"
        "/oil\n\n"
        "Rooms keep threads apart so messages do not mix:\n"
        "/ask/ — House\n"
        "/ask/vehicles — Vehicles\n"
        "/ask/inventory — Inventory\n"
        "/ask/tools — Tools\n"
        "/ask/basket — Basket\n"
        "/ask/due — Due\n"
        "/ask/help — this list\n\n"
        "Trips: “start a trip in my blue tundra with 81200 miles from Odessa to Lubbock” "
        "then “I’m home with 81650 miles.” That writes the day on the truck’s Log tab and updates miles.\n\n"
        "Writes show a plan first. Allow, don’t, “always allow” (simple work runs free), or “always ask.” "
        "/allow and /confirm switch that too.\n\n"
        "Sort inventory: “sort the inventory” files food into Fridge, Pantry, and the other rooms. It does not dump the list.\n\n"
        f"You are in {here['title']}. {here['hint']}"
    )


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
