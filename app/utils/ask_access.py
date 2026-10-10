"""Who can use Ask, and which chores a child can finish from the chat.

Page permissions stay as they are. Inside Ask, a child can do everyday
household work: shopping, inventory, reminders, notes, logs, and oil.
The vault, people, legal papers, settings, and deleting a vehicle stay
with whoever already has that permission on the page.
"""
from __future__ import annotations

from flask_login import current_user

from app.utils.permissions import can, role_of

# Not vault, members, legal, settings, leaders, or edit_meta.
CHILD_CHAT_PERMS = frozenset({"scan", "view", "edit_grocery", "maintain", "photo"})


def ask_can(action: str, user=None) -> bool:
    """Page permission, or an everyday chore a child may do from Ask."""
    if can(action, user):
        return True
    u = user if user is not None else current_user
    try:
        signed_in = bool(getattr(u, "is_authenticated", False))
    except Exception:
        signed_in = False
    if not signed_in:
        return False
    return role_of(u) == "child" and action in CHILD_CHAT_PERMS
