"""Add, password, and remove people in this household."""
from __future__ import annotations

from sqlalchemy.orm.attributes import flag_modified

from app.builddb.builddb import db
from app.utils.permissions import can


def can_manage_people(user=None) -> bool:
    from flask_login import current_user

    u = user if user is not None else current_user
    return can("members", u) or bool(getattr(u, "is_leader", False))


def _actor_can(user=None) -> bool:
    return can_manage_people(user)


def set_login_password(target, raw: str | None = None) -> tuple[bool, str, str]:
    from app.utils.household_mail import random_login_password

    if target is None or not getattr(target, "is_active", True):
        return False, "", "That person is already out of the house."
    password = ("" if raw is None else str(raw)).strip() or random_login_password()
    if len(password) < 8:
        return False, "", "Password needs at least 8 characters, or leave it blank and we make one."
    target.set_password(password)
    target.failed_login_attempts = 0
    target.account_locked_until = None
    db.session.commit()
    name = target.name or target.username
    return True, password, f"{name}'s password is updated. Copy it from the window."


def remove_member(target, *, by=None) -> tuple[bool, str]:
    from flask_login import current_user

    from app.builddb.table_users import User
    from app.utils.activity import record
    from app.utils.leaders import leader_count

    if target is None or not getattr(target, "is_active", True):
        return False, "That person is already out of the house."
    actor = by if by is not None else current_user
    if getattr(actor, "id", None) == target.id:
        return False, "You cannot remove yourself."
    hid = int(target.household_id)
    if target.is_leader and leader_count(hid) <= 1:
        return False, "Promote another leader before removing this person."
    active_n = User.query.filter_by(household_id=hid, is_active=True).count()
    if active_n <= 1:
        return False, "A household needs at least one person. Delete the household instead."

    extra = dict(target.extra_data) if isinstance(target.extra_data, dict) else {}
    extra["removed_username"] = target.username
    extra["removed_email"] = target.email
    extra["removed_leader"] = bool(target.is_leader)
    extra["removed_role"] = target.role
    record(
        action="user.remove",
        summary=f"{getattr(actor, 'name', None) or getattr(actor, 'username', None) or 'Someone'} removed {target.name}",
        target_table="users",
        target_id=target.id,
        old_json={
            "username": target.username,
            "email": target.email,
            "is_leader": bool(target.is_leader),
            "role": target.role,
            "name": target.name,
        },
        reversible=True,
        user_id=getattr(actor, "id", None),
    )
    target.is_active = False
    target.is_leader = False
    target.email = None
    target.calendar_token = None
    target.username = f"removed_{target.id}"
    target.extra_data = extra
    try:
        flag_modified(target, "extra_data")
    except Exception:
        pass
    db.session.commit()
    return True, f"{extra.get('removed_username') or target.name} is out of the house."


def undo_remove(target, old: dict | None) -> tuple[bool, str]:
    from app.utils.identity import username_taken

    if target is None:
        return False, "Can't find that person."
    old = old if isinstance(old, dict) else {}
    username = (old.get("username") or "").strip()
    if not username:
        extra = target.extra_data if isinstance(target.extra_data, dict) else {}
        username = (extra.get("removed_username") or "").strip()
    if not username:
        return False, "No username to restore."
    if username_taken(target.household_id, username, exclude_id=target.id):
        return False, f"{username} is already used in this household."
    email = (old.get("email") or "").strip() or None
    if email:
        from app.builddb.table_users import User

        clash = User.query.filter(User.email == email, User.id != target.id).first()
        if clash:
            email = None
    target.is_active = True
    target.username = username
    target.email = email
    if old.get("is_leader") and (target.role or "") != "child":
        target.is_leader = True
    extra = dict(target.extra_data) if isinstance(target.extra_data, dict) else {}
    extra.pop("removed_username", None)
    extra.pop("removed_email", None)
    extra.pop("removed_leader", None)
    extra.pop("removed_role", None)
    target.extra_data = extra or None
    try:
        flag_modified(target, "extra_data")
    except Exception:
        pass
    db.session.commit()
    return True, f"{target.name} is back in the house."
