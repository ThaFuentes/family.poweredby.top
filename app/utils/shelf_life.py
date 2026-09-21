"""Typical use-by when nobody typed a date. Food, plus chemicals that actually expire."""
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

_MEAT = (
    "chicken",
    "beef",
    "pork",
    "turkey",
    "steak",
    "sausage",
    "bacon",
    "ham",
    "ribs",
    "roast",
    "hamburger",
    "ground beef",
    "ground turkey",
    "ground pork",
    "meatball",
    "hot dog",
    "hotdog",
    "brisket",
    "lamb",
    "fish",
    "salmon",
    "shrimp",
    "meat",
)


def is_meat(name="", category="", kind="") -> bool:
    hay = f"{name} {category} {kind}".lower()
    return any(w in hay for w in _MEAT)


def guess_shelf_days(name="", category="", kind="", location="", frozen=None) -> int | None:
    kind = (kind or "").strip().lower()
    loc = (location or "").lower()
    hay = f"{name} {category} {kind} {location}".lower()
    if any(
        w in hay
        for w in (
            "bug spray",
            "insecticide",
            "pesticide",
            "ant killer",
            "wasp",
            "roach",
            "mosquito",
            "repellent",
            "raid",
            "fly spray",
            "weed killer",
        )
    ):
        return 730
    if any(w in hay for w in ("bleach", "disinfectant", "lysol", "clorox", "hydrogen peroxide")):
        return 365
    if "sunscreen" in hay or "spf" in hay:
        return 365
    if kind == "motor_oil" or any(w in hay for w in ("motor oil", "engine oil")):
        return 1825
    if any(w in hay for w in ("coolant", "air filter", "cabin filter", "car battery", "wiper")):
        return None
    if kind in _NOT_FOOD:
        return None
    if any(w in hay for w in ("milk", "half and half", "creamer", "yogurt", "cottage cheese", "sour cream")):
        return 10
    if "egg" in hay:
        return 21
    meat = is_meat(name, category, kind)
    frozen_here = frozen is True or "frozen" in hay or loc == "freezer"
    if meat and frozen_here:
        return 180
    if meat:
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
    if loc in ("fridge", "refrigerator"):
        return 14
    if kind in ("food", "drink", "pet", "unknown", ""):
        return 90
    return 90


def apply_shelf_life(item, g, *, force: bool = False) -> str | None:
    from app.utils.lots import apply_guess, extra_of, has_manual_lot, soonest

    extra = extra_of(g)
    if extra.get("expires_cleared") and not force:
        day = soonest(g)
        return day.isoformat() if day else extra.get("expires_on")
    if has_manual_lot(g) and not force:
        day = soonest(g)
        return day.isoformat() if day else extra.get("expires_on")
    kind = extra.get("kind") if isinstance(extra.get("kind"), str) else ""
    name = getattr(item, "name", "") or ""
    category = getattr(item, "category", "") or ""
    loc = getattr(g, "default_location", "") or ""
    if is_meat(name, category, kind) and extra.get("frozen") is None:
        if loc.lower() == "freezer":
            extra["frozen"] = True
            from sqlalchemy.orm.attributes import flag_modified

            g.extra_data = extra
            try:
                flag_modified(g, "extra_data")
            except Exception:
                pass
        else:
            extra["ask_frozen"] = True
            from sqlalchemy.orm.attributes import flag_modified

            g.extra_data = extra
            try:
                flag_modified(g, "extra_data")
            except Exception:
                pass
            day = soonest(g)
            return day.isoformat() if day else extra.get("expires_on")
    days = guess_shelf_days(
        name=name,
        category=category,
        kind=kind or "",
        location=loc,
        frozen=extra.get("frozen"),
    )
    if not days:
        day = soonest(g)
        return day.isoformat() if day else extra.get("expires_on")
    guessed = date.today() + timedelta(days=days)
    extra = extra_of(g)
    extra.pop("ask_frozen", None)
    extra["expires_days"] = days
    from sqlalchemy.orm.attributes import flag_modified

    g.extra_data = extra
    try:
        flag_modified(g, "extra_data")
    except Exception:
        pass
    return apply_guess(g, guessed, force=force)


def set_meat_storage(item, g, *, frozen: bool) -> str | None:
    extra = dict(g.extra_data or {}) if isinstance(getattr(g, "extra_data", None), dict) else {}
    extra["frozen"] = bool(frozen)
    extra.pop("ask_frozen", None)
    extra.pop("expires_cleared", None)
    g.extra_data = extra
    if frozen:
        if not (g.default_location or "").strip():
            g.default_location = "freezer"
    elif not (g.default_location or "").strip():
        g.default_location = "fridge"
    return apply_shelf_life(item, g, force=True)
