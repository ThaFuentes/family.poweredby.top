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


def _save_extra(g, extra: dict) -> None:
    from sqlalchemy.orm.attributes import flag_modified

    g.extra_data = extra
    try:
        flag_modified(g, "extra_data")
    except Exception:
        pass


def _clamp_days(raw) -> int | None:
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    if n < 1 or n > 3650:
        return None
    return n


def ai_shelf_days(item, g, household=None) -> int | None:
    """Typical days from the household AI key. Cached on the grocery row."""
    from app.utils.lots import extra_of

    extra = extra_of(g)
    if extra.get("ai_shelf_none"):
        return None
    cached = _clamp_days(extra.get("ai_shelf_days"))
    if cached:
        return cached
    if household is None:
        hid = getattr(item, "household_id", None)
        if hid:
            try:
                from app.builddb.table_households import Household

                household = Household.query.get(int(hid))
            except Exception:
                household = None
    if household is None:
        return None
    try:
        from app.utils.ai import complete_json, get_ai_config
    except Exception:
        return None
    try:
        cfg = get_ai_config(household, household_only=True)
    except Exception:
        return None
    if not cfg.get("ready"):
        return None
    name = getattr(item, "name", "") or ""
    brand = getattr(g, "brand", "") or ""
    loc = getattr(g, "default_location", "") or ""
    kind = extra.get("kind") if isinstance(extra.get("kind"), str) else ""
    frozen = extra.get("frozen")
    prompt = (
        f"Product: {name}\n"
        f"Brand: {brand}\n"
        f"Kind: {kind}\n"
        f"Where: {loc}\n"
        f"Frozen: {frozen}\n"
        "Typical unopened household shelf life from the day it is brought home, "
        "if nobody typed the printed date. JSON only: "
        '{"days":730,"note":"unopened bug spray, about 2 years"}. '
        "days is an integer 1-3650, or null if it does not expire "
        "(toilet paper, trash bags, tools). "
        "Bug spray/pesticide ~2 years, motor oil ~5 years unopened, "
        "sunscreen ~1 year, bleach ~1 year, milk fridge ~10 days, "
        "canned ~2 years, AA batteries ~5 years. No markdown."
    )
    try:
        ok, data = complete_json(
            prompt,
            system="Household pantry dating. Short JSON only. Not a chatbot.",
            max_tokens=160,
            timeout=8,
            household=household,
            household_only=True,
        )
    except Exception:
        return None
    if not ok or not isinstance(data, dict) or data.get("error"):
        return None
    days = _clamp_days(data.get("days"))
    if days is None:
        years = data.get("years")
        try:
            y = float(years)
        except (TypeError, ValueError):
            y = 0
        if y > 0:
            days = _clamp_days(int(round(y * 365)))
    extra = extra_of(g)
    note = str(data.get("note") or "").strip()[:160]
    if days:
        extra["ai_shelf_days"] = days
        extra.pop("ai_shelf_none", None)
        if note:
            extra["ai_shelf_note"] = note
        extra["expires_days_source"] = "ai"
        _save_extra(g, extra)
        return days
    extra["ai_shelf_none"] = True
    extra.pop("ai_shelf_days", None)
    _save_extra(g, extra)
    return None


def apply_shelf_life(item, g, *, force: bool = False, household=None) -> str | None:
    from app.utils.lots import apply_guess, extra_of, soonest, undated_qty

    extra = extra_of(g)
    if extra.get("expires_cleared") and not force:
        day = soonest(g)
        return day.isoformat() if day else extra.get("expires_on")
    if not force and undated_qty(g) <= 0:
        day = soonest(g)
        return day.isoformat() if day else extra.get("expires_on")
    kind = extra.get("kind") if isinstance(extra.get("kind"), str) else ""
    name = getattr(item, "name", "") or ""
    category = getattr(item, "category", "") or ""
    loc = getattr(g, "default_location", "") or ""
    if is_meat(name, category, kind) and extra.get("frozen") is None:
        if loc.lower() == "freezer":
            extra["frozen"] = True
            _save_extra(g, extra)
        else:
            extra["ask_frozen"] = True
            _save_extra(g, extra)
            day = soonest(g)
            return day.isoformat() if day else extra.get("expires_on")
    days = guess_shelf_days(
        name=name,
        category=category,
        kind=kind or "",
        location=loc,
        frozen=extra.get("frozen"),
    )
    source = "typical"
    if not days:
        days = ai_shelf_days(item, g, household=household)
        source = "ai" if days else source
    if not days:
        day = soonest(g)
        return day.isoformat() if day else extra.get("expires_on")
    guessed = date.today() + timedelta(days=days)
    extra = extra_of(g)
    extra.pop("ask_frozen", None)
    extra["expires_days"] = days
    extra["expires_days_source"] = source
    _save_extra(g, extra)
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
