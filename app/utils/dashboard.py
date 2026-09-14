"""Per-person home: which tiles show, and where Family OS opens."""
from __future__ import annotations

from flask import url_for
from sqlalchemy.orm.attributes import flag_modified

STARTS = (
    ("home", "Home"),
    ("scan", "Scan"),
    ("groceries", "Pantry"),
    ("basket", "Basket"),
    ("house", "House"),
    ("tools", "Tools"),
    ("vehicles", "Vehicles"),
    ("notes", "Notes"),
    ("find", "Find"),
    ("reminders", "Reminders"),
)

TILES = (
    ("scan", "Scan"),
    ("groceries", "Pantry"),
    ("basket", "Basket"),
    ("house", "House"),
    ("tools", "Tools"),
    ("vehicles", "Vehicles"),
    ("sort", "Sort"),
    ("notes", "Notes"),
    ("legal", "Records"),
    ("reminders", "Reminders"),
)

CHILD_STARTS = (("home", "Home"), ("scan", "Scan"))
CHILD_TILES = ("scan", "groceries", "basket", "notes", "find", "reminders")

_ENDPOINTS = {
    "home": "home.home",
    "scan": "scan.scan_page",
    "groceries": "groceries.index",
    "basket": "groceries.grocery_list",
    "house": "house.index",
    "tools": "tools.index",
    "vehicles": "vehicles.index",
    "notes": "notes.index",
    "find": "find.index",
    "reminders": "reminders.index",
}


def _blob(user) -> dict:
    extra = getattr(user, "extra_data", None)
    extra = extra if isinstance(extra, dict) else {}
    dash = extra.get("dashboard")
    return dict(dash) if isinstance(dash, dict) else {}


def _is_child(user) -> bool:
    return (getattr(user, "role", None) or "").strip().lower() == "child"


def allowed_starts(user) -> tuple:
    return CHILD_STARTS if _is_child(user) else STARTS


def allowed_tiles(user) -> tuple:
    if _is_child(user):
        return tuple((k, lab) for k, lab in TILES if k in CHILD_TILES)
    return TILES


def default_start(user) -> str:
    return "scan" if _is_child(user) else "home"


def dashboard_prefs(user) -> dict:
    blob = _blob(user)
    starts = {k for k, _ in allowed_starts(user)}
    start = (blob.get("start") or "").strip() or default_start(user)
    if start not in starts:
        start = default_start(user)
    allowed = [k for k, _ in allowed_tiles(user)]
    raw = blob.get("tiles")
    if isinstance(raw, list) and raw:
        tiles = [t for t in raw if t in allowed]
        if not tiles:
            tiles = list(allowed)
    else:
        tiles = list(allowed)
    show_needs = blob.get("show_needs")
    if show_needs is None:
        show_needs = True
    return {
        "start": start,
        "tiles": tiles,
        "tile_set": set(tiles),
        "show_needs": bool(show_needs),
        "starts": allowed_starts(user),
        "tile_choices": allowed_tiles(user),
    }


def start_endpoint(user) -> str:
    prefs = dashboard_prefs(user)
    return _ENDPOINTS.get(prefs["start"]) or "home.home"


def start_url(user) -> str:
    try:
        return url_for(start_endpoint(user))
    except Exception:
        return url_for("home.home")


def save_dashboard(user, *, start: str, tiles: list[str] | None, show_needs: bool) -> dict:
    from app.builddb.builddb import db

    starts = {k for k, _ in allowed_starts(user)}
    start = (start or "").strip() or default_start(user)
    if start not in starts:
        start = default_start(user)
    allowed = [k for k, _ in allowed_tiles(user)]
    if tiles is None:
        kept = list(allowed)
    else:
        kept = [t for t in tiles if t in allowed]
        if not kept:
            kept = list(allowed)
    extra = dict(user.extra_data) if isinstance(getattr(user, "extra_data", None), dict) else {}
    extra["dashboard"] = {
        "start": start,
        "tiles": kept,
        "show_needs": bool(show_needs),
    }
    user.extra_data = extra
    flag_modified(user, "extra_data")
    db.session.add(user)
    db.session.commit()
    return dashboard_prefs(user)
