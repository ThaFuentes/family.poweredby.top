"""Ask write confirm: show the plan, then allow or don’t.

Household setting `ask_confirm` is `ask` (default) or `allow` (run free).
Chat can switch it with “always allow” / “always ask”, or /allow and /confirm.
People, vault cards, and deleting a vehicle still ask in allow mode.
"""
from __future__ import annotations

import re

from flask import has_request_context, session
from flask_login import current_user

SESSION_WRITE_PENDING = "family_ask_write_pending"

ALWAYS_ASK_TOOLS = frozenset(
    {
        "member_remove",
        "member_role",
        "member_password",
        "vault_save",
    }
)

_YES = re.compile(
    r"^\s*(?:please\s+)?(?:"
    r"(?:yes|yeah|yep|yup|ok|okay|sure|allow|allowed)"
    r"(?:\s*,?\s*(?:please\s+)?(?:do it|go ahead|allow(?:\s+this)?|save(?:\s+it|\s+that)?))?|"
    r"do it|go ahead|allow this"
    r")\s*[.!]?\s*$",
    re.I,
)
_NO = re.compile(
    r"^\s*(?:no|nope|cancel|never mind|don't|do not|disallow|don't allow|dont allow)\b",
    re.I,
)
_ALLOW_MODE = re.compile(
    r"\b(always allow|run free|stop asking|don't ask(?: me)?|dont ask(?: me)?|just do it from now on)\b",
    re.I,
)
_ASK_MODE = re.compile(
    r"\b(always ask|ask(?: me)? first|start asking|confirm first)\b",
    re.I,
)


def _trim(value, cap: int = 200) -> str:
    return str(value or "").strip()[:cap]


def confirm_mode() -> str:
    from app.utils.household_ai import household_config, normalize_ask_confirm

    try:
        house = getattr(current_user, "household", None)
        if house is None:
            return "ask"
        return normalize_ask_confirm(household_config(house).get("ask_confirm"))
    except Exception:
        return "ask"


def set_mode(mode: str) -> dict:
    from app.utils.household_ai import set_household_ask_confirm

    house = getattr(current_user, "household", None)
    if house is None:
        return {"ok": False, "say": "Could not save that Ask setting.", "did": [], "vault_locked": False}
    cfg = set_household_ask_confirm(house, mode)
    on = (cfg.get("ask_confirm") or "ask") == "allow"
    if on:
        say = (
            "Okay. I’ll do simple adds and changes without asking. "
            "I’ll still check with you before people, vault cards, or deleting a vehicle."
        )
    else:
        say = "Okay. I’ll show the plan and wait for Allow before I add, change, or delete."
    return {"ok": True, "say": say, "did": [], "vault_locked": False, "ask_confirm": "allow" if on else "ask"}


def write_needs_confirm(tool: str, args: dict | None = None) -> bool:
    args = args if isinstance(args, dict) else {}
    if args.get("confirmed"):
        return False
    from app.utils.ask import WRITE_TOOLS

    if tool not in WRITE_TOOLS:
        return False
    if tool == "vault_unlock":
        return False
    mode = confirm_mode()
    if mode == "allow":
        if tool in ALWAYS_ASK_TOOLS:
            return True
        if tool == "item_remove":
            return _remove_is_vehicle(args)
        return False
    return True


def should_hold_tool(tool: str, args: dict | None = None, *, has_photo: bool = False) -> bool:
    args = args if isinstance(args, dict) else {}
    if not write_needs_confirm(tool, args):
        return False
    if tool == "place":
        return False
    if tool == "member_add" and not (_trim(args.get("username"), 80) and _trim(args.get("name"), 80)):
        return False
    if tool == "inventory" and not _inventory_exists(args):
        return False
    if tool == "item_remove" and not _trim(args.get("q") or args.get("name") or args.get("item"), 200):
        return False
    return True


def _inventory_exists(args: dict) -> bool:
    from app.utils.ask import _find_items

    q = _trim(args.get("q") or args.get("name") or args.get("id"), 200)
    if not q:
        return False
    return bool(_find_items(q, "grocery"))


def _remove_is_vehicle(args: dict) -> bool:
    from app.utils.ask import _pick_for_remove

    q = _trim(args.get("q") or args.get("name") or args.get("item"), 200)
    if not q:
        return False
    item, err = _pick_for_remove(q)
    return item is not None and getattr(item, "item_type", "") == "vehicle" and err is None


def _looks_like_sentence(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    if "?" in t or len(t) > 48:
        return True
    if re.search(r"\b(can you|please|start|trip|miles|with)\b", t, re.I) and len(t.split()) > 4:
        return True
    return False


def _trip_who(args: dict) -> str:
    hint = _trim(args.get("item") or args.get("name") or "", 80)
    try:
        from app.utils.ask_do import _trip_vehicle

        item, _err = _trip_vehicle(args)
        if item is not None:
            return item.name
    except Exception:
        pass
    if hint and not _looks_like_sentence(hint):
        return hint
    return "the truck"


def _fmt_miles(raw) -> str:
    s = str(raw or "").replace(",", "").strip()
    if not s:
        return ""
    try:
        return f"{int(float(s)):,}"
    except (TypeError, ValueError):
        return s


def plan_line(tool: str, args: dict | None = None) -> str:
    args = args if isinstance(args, dict) else {}
    name = _trim(
        args.get("name") or args.get("title") or args.get("q") or args.get("item") or args.get("what"),
        120,
    )
    if tool == "item_remove":
        from app.utils.ask import _pick_for_remove

        item, err = _pick_for_remove(_trim(args.get("q") or args.get("name") or args.get("item"), 200))
        if err:
            return str(err.get("hint") or err.get("error") or "I’ll remove that item.")
        if item is None:
            return "I’ll remove that item."
        kind = {"grocery": "inventory", "tool": "tools", "vehicle": "vehicles"}.get(
            item.item_type, item.item_type
        )
        return f"I’ll remove {item.name} from {kind}."
    if tool == "trip_save":
        action = _trim(args.get("action") or args.get("op") or "", 20).lower()
        who = _trip_who(args)
        if action in ("end", "home", "done", "close", "finish") or args.get("end") or args.get("end_miles"):
            miles = _fmt_miles(args.get("reading") or args.get("end") or args.get("end_miles") or args.get("miles"))
            truck = f" on {who}" if who else ""
            at = f" at {miles} miles" if miles else ""
            return f"End the open trip{truck}{at}."
        origin = _trim(args.get("origin") or args.get("from"), 80)
        dest = _trim(args.get("dest") or args.get("to"), 80)
        miles = _fmt_miles(args.get("reading") or args.get("start") or args.get("start_miles") or args.get("miles"))
        route = ""
        if origin and dest:
            route = f" from {origin} to {dest}"
        elif origin or dest:
            route = f" {origin or dest}"
        at = f" at {miles} miles" if miles else ""
        return f"Start a trip on {who}{route}{at}."
    if tool == "inventory":
        action = _trim(args.get("action") or "restock", 20).lower() or "restock"
        loc = _trim(args.get("place") or args.get("location"), 80)
        qty = _trim(args.get("amount") or args.get("qty") or args.get("quantity"), 20)
        if action == "place" or (loc and action in ("place", "set", "restock")):
            bit = f"Put {name or 'that'} in {loc}" if loc else f"Update {name or 'that'}"
            if qty and action == "set":
                bit += f" and set the count to {qty}"
            return bit + "."
        return f"I’ll {action} {name or 'that food'} in inventory."
    if tool == "member_add":
        return f"I’ll add {name or args.get('username') or 'a person'} to this house."
    if tool == "member_remove":
        return f"I’ll remove {args.get('username') or name or 'that person'} from this house."
    if tool == "member_role":
        return f"I’ll set {args.get('username') or name} to {args.get('role') or 'a new role'}."
    if tool == "member_password":
        return f"I’ll set a new password for {args.get('username') or name or 'that person'}."
    if tool == "vault_save":
        return f"I’ll save {name or 'a card'} in the vault."
    if tool == "tool_save":
        return f"I’ll save a tool named {name or 'that tool'}."
    if tool == "vehicle_save":
        return f"I’ll save a vehicle{(' named ' + name) if name else ''}."
    if tool == "place":
        return f"I’ll file {name or args.get('barcode') or 'that'}."
    if tool == "note_save":
        return f"I’ll save a note{(' — ' + name) if name else ''}."
    if tool == "basket_add":
        names = args.get("names") or name
        if isinstance(names, list):
            names = ", ".join(str(x) for x in names[:6] if x)
        return f"I’ll add {names or 'those'} to the basket."
    if tool == "reminder_save":
        return f"I’ll add a reminder for {name or 'that'}."
    if tool == "oil_save":
        return f"I’ll save the oil spec on {name or 'that machine'}."
    if tool == "log_save":
        return f"I’ll log {args.get('kind') or 'this'} on {name or 'that machine'}."
    if tool == "part_save":
        return f"I’ll put {name or 'that part'} on {args.get('vehicle') or 'the house'}."
    if tool == "expire_save":
        return f"I’ll set a use-by date on {name or 'that food'}."
    if tool == "expire_guess":
        return "I’ll put typical use-by dates on undated food."
    if tool == "inventory_sort":
        if str(args.get("only_empty") or "1") in ("0", "false", "no", "all"):
            return "Re-file every grocery into Fridge, Pantry, and the other rooms."
        return "Put inventory with no room yet into Fridge, Pantry, and the other rooms."
    if tool == "legal_save":
        return f"I’ll save {name or 'that paper'}."
    if tool == "basket_match":
        return "I’ll match that scan to a basket row."
    return f"I’ll {tool.replace('_', ' ')}{(' — ' + name) if name else ''}."


def hold_writes(items: list) -> dict:
    rows = []
    for item in items or []:
        if isinstance(item, (tuple, list)) and len(item) >= 2:
            tool, args = item[0], item[1] if isinstance(item[1], dict) else {}
        elif isinstance(item, dict):
            tool, args = item.get("tool") or "", item.get("args") if isinstance(item.get("args"), dict) else {}
        else:
            continue
        if not tool:
            continue
        rows.append({"tool": tool, "args": dict(args or {})})
    if has_request_context():
        session[SESSION_WRITE_PENDING] = {"items": rows}
    lines = [plan_line(row["tool"], row["args"]) for row in rows]
    if not lines:
        say = "Nothing to do."
    elif len(lines) == 1:
        say = lines[0] + "\nDoes that look right?"
    else:
        say = "I’ll do this:\n" + "\n".join(f"· {ln}" for ln in lines) + "\nDoes that look right?"
    return {
        "ok": True,
        "say": say,
        "confirm": True,
        "did": [],
        "vault_locked": False,
    }


def _speak(tool: str, result: dict) -> str:
    from app.utils.ask import _speak_result

    if not isinstance(result, dict):
        return str(result or "")
    if result.get("need") or result.get("error"):
        return str(result.get("hint") or result.get("error") or "Could not do that.")
    spoken = _speak_result(tool, result)
    return spoken or str(result.get("did") or result.get("say") or "Done.")


def apply_held() -> dict:
    pending = session.pop(SESSION_WRITE_PENDING, None) if has_request_context() else None
    items = (pending or {}).get("items") if isinstance(pending, dict) else None
    if not items:
        return {
            "ok": True,
            "say": "Nothing waiting.",
            "did": [],
            "vault_locked": False,
        }
    from app.utils.ask import (
        WRITE_TOOLS,
        _pick_named_item,
        _soft_remove_item,
        _with_issued_login,
        run_tool,
    )

    says = []
    did = []
    notes = []
    vault_locked = False
    for row in items:
        tool = row.get("tool") or ""
        args = dict(row.get("args") or {})
        args["confirmed"] = True
        result = run_tool(tool, args)
        if tool == "item_remove" and result.get("need") and result.get("id"):
            item, err = _pick_named_item(str(result.get("id")), (result.get("kind") or "grocery",))
            if item is not None and err is None:
                result = _soft_remove_item(item)
        if not isinstance(result, dict):
            result = {"ok": False, "error": str(result or "")}
        notes.append({"tool": tool, "result": result})
        says.append(_speak(tool, result))
        if result.get("need") == "vault_unlock" or result.get("vault_locked"):
            vault_locked = True
        if result.get("ok") and tool in WRITE_TOOLS:
            did.append(
                {
                    "tool": tool,
                    "href": result.get("href") or "",
                    "title": result.get("title") or result.get("name") or "",
                }
            )
    say = _with_issued_login("\n".join(s for s in says if s).strip() or "Done.", notes)
    return {
        "ok": True,
        "say": say,
        "confirm": False,
        "did": did,
        "vault_locked": vault_locked,
    }


def cancel_held() -> dict:
    pending = session.pop(SESSION_WRITE_PENDING, None) if has_request_context() else None
    items = (pending or {}).get("items") if isinstance(pending, dict) else []
    label = "that"
    if items:
        label = plan_line(items[0].get("tool") or "", items[0].get("args") or {})
        label = label[4:] if label.lower().startswith("i’ll ") or label.lower().startswith("i'll ") else label
    return {
        "ok": True,
        "say": f"Okay, I left {label} alone.",
        "did": [],
        "vault_locked": False,
        "confirm": False,
    }


def handle_reply(text: str) -> dict | None:
    raw = (text or "").strip()
    if not raw:
        return None
    pending = session.get(SESSION_WRITE_PENDING) if has_request_context() else None
    has_pending = isinstance(pending, dict) and pending.get("items")
    if has_pending:
        if _NO.search(raw):
            return cancel_held()
        if _ALLOW_MODE.search(raw):
            set_mode("allow")
            done = apply_held()
            extra = " Running free from now on for simple work."
            done["say"] = ((done.get("say") or "").rstrip() + extra).strip()
            done["ask_confirm"] = "allow"
            return done
        if _ASK_MODE.search(raw):
            set_mode("ask")
            held = hold_writes(pending.get("items") or [])
            held["say"] = "I’ll keep asking first.\n" + (held.get("say") or "")
            held["ask_confirm"] = "ask"
            return held
        if _YES.match(raw):
            return apply_held()
        return None
    if re.match(
        r"^\s*(always allow|run free|stop asking|don't ask|dont ask|just do it from now on)\b",
        raw,
        re.I,
    ):
        return set_mode("allow")
    if re.match(r"^\s*(always ask|ask(?: me)? first|start asking|confirm first)\b", raw, re.I):
        return set_mode("ask")
    return None
