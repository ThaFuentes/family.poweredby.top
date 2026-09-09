"""Household leaders — the only tenant people the platform may see.

Platform queries here return id, name, email. Never notes, pantry, photos, or scans.
"""
from __future__ import annotations

from sqlalchemy import func

from app.builddb.builddb import db
from app.builddb.table_households import Household
from app.builddb.table_users import User

CHILD = "child"


def leader_count(household_id: int) -> int:
    return int(
        User.query.filter_by(household_id=household_id, is_leader=True, is_active=True).count()
    )


def leaders_public(household_id: int) -> list[dict]:
    rows = (
        User.query.filter_by(household_id=household_id, is_leader=True, is_active=True)
        .with_entities(User.id, User.name, User.email)
        .order_by(User.id.asc())
        .all()
    )
    return [{"id": r.id, "name": r.name or "", "email": r.email or ""} for r in rows]


def people_count(household_id: int) -> int:
    return int(User.query.filter_by(household_id=household_id).count())


def find_in_household_by_email(household_id: int, email: str) -> User | None:
    ident = (email or "").strip().lower()
    if not ident:
        return None
    return User.query.filter(
        User.household_id == household_id,
        func.lower(User.email) == ident,
        User.is_active.is_(True),
    ).first()


def can_be_leader(user: User) -> tuple[bool, str]:
    if user is None:
        return False, "No such person in this household."
    if not user.is_active:
        return False, "That account is not active."
    if (user.role or "").strip().lower() == CHILD:
        return False, "A child cannot be a household leader."
    return True, ""


def set_leader(user: User, make_leader: bool) -> tuple[bool, str]:
    ok, msg = can_be_leader(user)
    if not ok:
        return False, msg
    if make_leader:
        if not (user.email or "").strip():
            return False, "Give them an email first so they can reset a password and get reminders."
        if user.is_leader:
            return True, f"{user.name} is already a leader."
        user.is_leader = True
        db.session.commit()
        return True, f"{user.name} is now a household leader."
    if not user.is_leader:
        return True, f"{user.name} is not a leader."
    if leader_count(user.household_id) <= 1:
        return False, "A household needs at least one leader."
    user.is_leader = False
    db.session.commit()
    return True, f"{user.name} is no longer a leader."


def fleet_cards() -> list[dict]:
    """One row per household. Leaders only — no other member PII."""
    houses = Household.query.order_by(Household.created_at.desc()).all()
    if not houses:
        return []
    ids = [h.id for h in houses]
    counts = dict(
        db.session.query(User.household_id, func.count(User.id))
        .filter(User.household_id.in_(ids))
        .group_by(User.household_id)
        .all()
    )
    leader_rows = (
        User.query.filter(User.household_id.in_(ids), User.is_leader.is_(True), User.is_active.is_(True))
        .with_entities(User.household_id, User.id, User.name, User.email)
        .order_by(User.id.asc())
        .all()
    )
    by_house: dict[int, list] = {hid: [] for hid in ids}
    for row in leader_rows:
        by_house.setdefault(row.household_id, []).append(
            {"id": row.id, "name": row.name or "", "email": row.email or ""}
        )
    cards = []
    for h in houses:
        cards.append(
            {
                "id": h.id,
                "name": h.name,
                "created_at": h.created_at,
                "is_active": bool(h.is_active),
                "people": int(counts.get(h.id) or 0),
                "leaders": by_house.get(h.id) or [],
            }
        )
    return cards
