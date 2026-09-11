"""Household handles and per-house usernames. Email is optional contact, not identity."""
from __future__ import annotations

import re

from sqlalchemy import func

HANDLE_RE = re.compile(r"^[a-z][a-z0-9]{1,31}$")
USER_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


def norm_handle(raw: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "", (raw or "").strip().lower())
    return s[:32]


def norm_username(raw: str) -> str:
    s = re.sub(r"[^a-z0-9_]+", "", (raw or "").strip().lower())
    return s[:32]


def valid_handle(raw: str) -> bool:
    return bool(HANDLE_RE.fullmatch(norm_handle(raw)))


def valid_username(raw: str) -> bool:
    return bool(USER_RE.fullmatch(norm_username(raw)))


def default_household_name(person_name: str) -> str:
    """Optional house label. People still type their own names."""
    parts = (person_name or "").strip().split()
    if not parts:
        return "House"
    first = parts[0]
    if first.lower().endswith("s"):
        return f"{first}' house"
    return f"{first}'s house"


def suggest_handle(name: str) -> str:
    s = norm_handle(name)
    if s.startswith(("the",)) and len(s) > 5:
        s = s[3:]
    for tail in ("house", "home", "family"):
        if s.endswith(tail) and len(s) > len(tail) + 1:
            s = s[: -len(tail)]
    return s or "house"


def unique_handle(name: str, *, exclude_id=None) -> str:
    from app.builddb.table_households import Household

    base = suggest_handle(name)
    if not valid_handle(base):
        base = "house"
    candidate = base
    n = 2
    while True:
        q = Household.query.filter(func.lower(Household.handle) == candidate)
        if exclude_id:
            q = q.filter(Household.id != exclude_id)
        if q.first() is None:
            return candidate
        candidate = f"{base}{n}"[:32]
        n += 1


def username_taken(household_id: int, username: str, *, exclude_id=None) -> bool:
    from app.builddb.table_users import User

    u = norm_username(username)
    if not u:
        return True
    q = User.query.filter(
        User.household_id == household_id,
        func.lower(User.username) == u,
    )
    if exclude_id:
        q = q.filter(User.id != exclude_id)
    return q.first() is not None


def find_household(handle_or_name: str):
    from app.builddb.table_households import Household

    raw = (handle_or_name or "").strip()
    if not raw:
        return None
    handle = norm_handle(raw)
    if handle:
        row = Household.query.filter(func.lower(Household.handle) == handle).first()
        if row:
            return row
    return Household.query.filter(func.lower(Household.name) == raw.lower()).first()


def find_login(username: str, household: str | None = None):
    """Username is per household. Email still works as a shortcut if they set one."""
    from app.builddb.table_users import User

    ident = (username or "").strip()
    house = (household or "").strip()
    if not ident:
        return None
    if "@" in ident:
        return User.query.filter(func.lower(User.email) == ident.lower()).first()
    uname = norm_username(ident)
    if house:
        h = find_household(house)
        if h is None:
            return None
        return User.query.filter(
            User.household_id == h.id,
            func.lower(User.username) == uname,
        ).first()
    matches = User.query.filter(func.lower(User.username) == uname).all()
    if len(matches) == 1:
        return matches[0]
    return None
