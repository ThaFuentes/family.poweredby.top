"""House systems — same shop-file pattern as the vehicle, for the building."""
from __future__ import annotations

from app.utils.vehicle_systems import group_parts, install_part, systems_payload

HOUSE_SYSTEMS: tuple[tuple[str, str, str], ...] = (
    ("hvac", "HVAC", "Filter size, furnace, A/C"),
    ("water", "Water", "Heater, softener, whole-house filter"),
    ("safety", "Safety", "Smoke, CO, extinguisher"),
    ("electrical", "Electrical", "Panel, breakers, generator"),
    ("plumbing", "Plumbing", "Main shutoff, sump, toilets"),
    ("appliances", "Appliances", "Fridge, washer, dryer, dishwasher"),
    ("other", "Other", "Anything else in the house"),
)

HOUSE_SLOTS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "hvac": (
        ("filter", "HVAC filter", "Size on the frame — 16x25x1"),
        ("furnace", "Furnace", "Model / serial"),
        ("ac", "A/C outdoor unit", "Photo the data plate"),
        ("thermostat", "Thermostat", ""),
    ),
    "water": (
        ("heater", "Water heater", "Gas / electric, gallons"),
        ("anode", "Anode rod", ""),
        ("softener", "Softener / salt", ""),
        ("filter", "Whole-house filter", ""),
    ),
    "safety": (
        ("smoke", "Smoke detectors", "How many, last battery"),
        ("co", "CO detectors", ""),
        ("extinguisher", "Fire extinguisher", "Expiry"),
        ("radon", "Radon", ""),
    ),
    "electrical": (
        ("panel", "Breaker panel", "Photo the legend"),
        ("generator", "Generator", "Fuel, oil"),
        ("battery_backup", "Battery backup", ""),
    ),
    "plumbing": (
        ("shutoff", "Main shutoff", "Where it is"),
        ("sump", "Sump pump", ""),
        ("disposal", "Disposal", ""),
    ),
    "appliances": (
        ("fridge", "Fridge / freezer", "Filter, ice maker"),
        ("washer", "Washer", ""),
        ("dryer", "Dryer", "Vent last cleaned"),
        ("dishwasher", "Dishwasher", ""),
        ("range", "Range / oven", ""),
    ),
    "other": (("misc", "Other", "Name it"),),
}


def house_systems_payload() -> list[dict]:
    return systems_payload(systems=HOUSE_SYSTEMS, slots=HOUSE_SLOTS)


def group_house_parts(parts) -> list[dict]:
    return group_parts(parts, systems=HOUSE_SYSTEMS, slots=HOUSE_SLOTS)


def install_house_part(**kwargs):
    kwargs["catalog_slots"] = HOUSE_SLOTS
    return install_part(**kwargs)


def ensure_house_item(household_id: int, user_id=None, name: str | None = None):
    """One 'The house' catalog row per household. Reused, never duplicated."""
    from app.builddb.builddb import db
    from app.builddb.table_items import Item
    from app.utils.qr_labels import item_payload

    row = (
        Item.query.filter_by(household_id=household_id, item_type="house")
        .order_by(Item.id.asc())
        .first()
    )
    if row:
        return row, False
    item = Item(
        household_id=household_id,
        name=(name or "The house")[:200],
        item_type="house",
        created_by=user_id,
    )
    db.session.add(item)
    db.session.flush()
    item.barcode = item_payload(household_id, item.id)
    return item, True
