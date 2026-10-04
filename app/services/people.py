"""People and household settings actions shared by the People page and Maya."""
from __future__ import annotations

from app.builddb.builddb import db


def set_member_role(user, role, *, actor) -> tuple[bool, str]:
    from app.builddb.table_users import ROLES
    from app.utils.leaders import leader_count

    if user.id == actor.id:
        return False, "You cannot change your own role here."
    role = (str(role or "")).strip().lower()
    if role not in ROLES:
        return False, "Invalid role."
    if role == "child" and user.is_leader:
        if leader_count(user.household_id) <= 1:
            return False, "Promote another leader before making this person a child."
        user.is_leader = False
    user.role = role
    return True, f"{user.name} is now {role}."


def rename_household(household, name) -> tuple[bool, str]:
    name = (str(name or "")).strip()
    if not name:
        return False, "Name your household. We will not name it for you."
    household.name = name[:150]
    return True, "Household name saved."
