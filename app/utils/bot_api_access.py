"""What this bot account may do through its API key.

The key is the bot's own Family account. A call can read or change only
what that account can already do in the app. A vault-only key still cannot
touch the house. A house key can open the vault only when this account can.
"""
from __future__ import annotations

from app.utils.bot_api_auth import api_error, api_user
from app.utils.permissions import can, role_of

ACCOUNT_ACTIONS = (
    "scan",
    "view",
    "edit_grocery",
    "maintain",
    "photo",
    "legal",
    "vault",
    "edit_meta",
    "members",
    "settings",
    "leaders",
    "override",
)


def account_can(*actions: str) -> bool:
    user = api_user()
    if user is None:
        return False
    return any(can(action, user) for action in actions)


def gate(*actions: str):
    """403 when this account cannot do any of these, else None."""
    if account_can(*actions):
        return None
    return api_error("This account cannot do that.", 403, "forbidden")


def account_snapshot() -> dict:
    user = api_user()
    flags = {action: bool(user and can(action, user)) for action in ACCOUNT_ACTIONS}
    return {
        "role": role_of(user) if user is not None else "",
        "is_leader": bool(getattr(user, "is_leader", False)) if user is not None else False,
        "can": flags,
    }


def inventory_write_allowed(item_type: str, data: dict, *, creating: bool) -> bool:
    """Same split the item and grocery pages use."""
    user = api_user()
    if user is None:
        return False
    if can("edit_meta", user):
        return True
    kind = (item_type or "grocery").strip().lower()
    if creating:
        if kind in ("grocery", "custom") and can("edit_grocery", user):
            return True
        if kind in ("tool", "vehicle", "house") and can("maintain", user):
            return True
        return False
    meta = {"name", "category", "notes", "barcode", "item_type"}
    stock = {"quantity", "restock_threshold", "location", "brand", "size", "unit"}
    touched = {key for key in (data or {}) if data.get(key) is not None or key in data}
    if touched & meta:
        if kind in ("grocery", "custom") and can("edit_grocery", user):
            return True
        if kind in ("tool", "vehicle", "house") and can("maintain", user):
            return True
        return False
    if can("edit_grocery", user) or can("maintain", user):
        return True
    if kind == "grocery" and can("scan", user) and (not touched or touched <= stock):
        return True
    return False


def note_edit_allowed(note) -> bool:
    """Author, or a leader / admin — the same rule as the Notes page."""
    user = api_user()
    if user is None or note is None:
        return False
    if int(getattr(note, "user_id", 0) or 0) == int(user.id):
        return True
    return bool(getattr(user, "is_admin", False) or getattr(user, "is_leader", False))
