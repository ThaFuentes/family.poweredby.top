"""Typical use-by when nobody typed a date. Food only."""
from __future__ import annotations

from datetime import date, timedelta

_NOT_FOOD = {
    "aa_battery",
    "car_battery",
    "motor_oil",
    "filter",
    "auto_part",
    "household",
    "beauty",
}


def guess_shelf_days(name="", category="", kind="", location="") -> int | None:
    kind = (kind or "").strip().lower()
    if kind in _NOT_FOOD:
        return None
    hay = f"{name} {category} {kind} {location}".lower()
    if any(w in hay for w in ("motor oil", "coolant", "air filter", "cabin filter", "car battery", "wiper")):
        return None
    if any(w in hay for w in ("milk", "half and half", "creamer", "yogurt", "cottage cheese", "sour cream")):
        return 10
    if "egg" in hay:
        return 21
    if any(w in hay for w in ("chicken", "beef", "pork", "turkey", "steak", "sausage", "bacon", "ground")):
        return 4
    if any(w in hay for w in ("bread", "bagel", "tortilla", "bun")):
        return 7
    if any(w in hay for w in ("lettuce", "spinach", "berry", "berries", "banana", "salad", "broccoli")):
        return 7
    if "frozen" in hay or (location or "").lower() == "freezer":
        return 180
    if any(w in hay for w in ("canned", "can of", "soup", "beans")):
        return 730
    if any(w in hay for w in ("cereal", "pasta", "rice", "flour", "sugar", "oat", "chip", "cracker", "cookie")):
        return 180
    if kind == "drink" or any(w in hay for w in ("juice", "soda")):
        return 120
    if kind == "pet" or "dog food" in hay or "cat food" in hay:
        return 180
    loc = (location or "").lower()
    if loc in ("fridge", "refrigerator"):
        return 14
    if kind in ("food", "drink", "pet", "unknown", ""):
        return 90
    return 90


def apply_shelf_life(item, g, *, force: bool = False) -> str | None:
    extra = dict(g.extra_data or {}) if isinstance(getattr(g, "extra_data", None), dict) else {}
    if extra.get("expires_cleared") and not force:
        return extra.get("expires_on")
    if extra.get("expires_on") and not extra.get("expires_guessed") and not force:
        return extra.get("expires_on")
    kind = extra.get("kind") if isinstance(extra.get("kind"), str) else ""
    days = guess_shelf_days(
        name=getattr(item, "name", "") or "",
        category=getattr(item, "category", "") or "",
        kind=kind or "",
        location=getattr(g, "default_location", "") or "",
    )
    if not days:
        return extra.get("expires_on")
    extra["expires_on"] = (date.today() + timedelta(days=days)).isoformat()
    extra["expires_guessed"] = True
    extra["expires_days"] = days
    g.extra_data = extra
    return extra["expires_on"]
