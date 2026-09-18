"""Free line icons for parts when there is no UPC photo. Original SVGs, no CDN."""
from __future__ import annotations

SLOT_ICONS = {
    "battery": "battery",
    "alternator": "alternator",
    "starter": "starter",
    "cables": "battery",
    "fuses": "cog",
    "headlights": "light",
    "tail_lights": "light",
    "oil": "oil",
    "oil_filter": "filter",
    "air_filter": "filter",
    "spark_plugs": "spark",
    "ignition_coils": "spark",
    "serpentine_belt": "belt",
    "timing": "belt",
    "pcv": "engine",
    "radiator": "radiator",
    "coolant": "oil",
    "hoses": "hose",
    "water_pump": "pump",
    "thermostat": "radiator",
    "fan": "radiator",
    "fuel_filter": "filter",
    "fuel_pump": "pump",
    "injectors": "fuel",
    "fuel_cap": "fuel",
    "trans_fluid": "oil",
    "trans_filter": "filter",
    "transfer_case": "cog",
    "diff_front": "cog",
    "diff_rear": "cog",
    "cv_axle": "cog",
    "clutch": "cog",
    "pads_front": "brake",
    "pads_rear": "brake",
    "rotors_front": "brake",
    "rotors_rear": "brake",
    "brake_fluid": "brake",
    "calipers": "brake",
    "tires": "tire",
    "spare": "tire",
    "tpms": "tire",
    "alignment": "tire",
    "wheels": "tire",
    "manifold": "exhaust",
    "catalytic": "exhaust",
    "o2_sensor": "exhaust",
    "muffler": "exhaust",
    "exhaust_pipe": "exhaust",
    "radio": "radio",
    "infotainment": "radio",
    "cameras": "radio",
    "sensors": "cog",
    "ecu": "cog",
    "alarm": "cog",
    "trailer_plug": "cog",
    "wipers": "wiper",
    "wiper_fluid": "wiper",
    "cabin_filter": "filter",
    "ac_compressor": "radiator",
    "ac_refrigerant": "radiator",
    "heater_core": "radiator",
    "shocks_front": "shock",
    "shocks_rear": "shock",
    "ps_fluid": "oil",
    "tie_rods": "shock",
    "ball_joints": "shock",
    "control_arms": "shock",
    "filter": "filter",
    "furnace": "radiator",
    "ac": "radiator",
    "heater": "radiator",
    "panel": "cog",
    "generator": "alternator",
}

NAME_HINTS = (
    ("alternator", "alternator"),
    ("battery", "battery"),
    ("starter", "starter"),
    ("radiator", "radiator"),
    ("coolant", "oil"),
    ("headlight", "light"),
    ("tail light", "light"),
    ("spark", "spark"),
    ("plug", "spark"),
    ("belt", "belt"),
    ("filter", "filter"),
    ("oil", "oil"),
    ("tire", "tire"),
    ("brake", "brake"),
    ("pad", "brake"),
    ("rotor", "brake"),
    ("muffler", "exhaust"),
    ("exhaust", "exhaust"),
    ("catalytic", "exhaust"),
    ("radio", "radio"),
    ("wiper", "wiper"),
    ("pump", "pump"),
    ("hose", "hose"),
    ("shock", "shock"),
    ("strut", "shock"),
)

SYSTEM_ICONS = {
    "electrical": "battery",
    "engine": "oil",
    "cooling": "radiator",
    "brakes": "brake",
    "tires": "tire",
    "exhaust": "exhaust",
    "fuel": "fuel",
    "electronics": "radio",
    "hvac": "filter",
    "body": "wiper",
    "drivetrain": "cog",
    "steering": "shock",
    "other": "cog",
}

KIND_ICONS = {
    "car_battery": "battery",
    "aa_battery": "battery",
    "motor_oil": "oil",
    "filter": "filter",
    "auto_part": "cog",
}

KNOWN = frozenset(
    {
        "battery",
        "alternator",
        "starter",
        "light",
        "radiator",
        "oil",
        "filter",
        "spark",
        "belt",
        "tire",
        "brake",
        "exhaust",
        "radio",
        "pump",
        "wiper",
        "cog",
        "engine",
        "fuel",
        "hose",
        "shock",
    }
)


def part_icon_key(part=None, *, slot=None, name=None, system=None, kind=None, default="cog") -> str:
    if part is not None:
        slot = slot or getattr(part, "slot", None)
        name = name or getattr(part, "name", None)
        system = system or getattr(part, "system", None)
    slot = (slot or "").strip().lower()
    if slot in SLOT_ICONS:
        return SLOT_ICONS[slot]
    blob = f"{name or ''} {kind or ''}".lower()
    for needle, key in NAME_HINTS:
        if needle in blob:
            return key
    kind = (kind or "").strip().lower()
    if kind in KIND_ICONS:
        return KIND_ICONS[kind]
    system = (system or "").strip().lower()
    if system in SYSTEM_ICONS:
        return SYSTEM_ICONS[system]
    return default if default in KNOWN or default == "" else "cog"


def icon_for(obj) -> str:
    """Jinja filter: VehiclePart, Item, or a slot/name string."""
    if obj is None:
        return ""
    if isinstance(obj, str):
        return part_icon_key(slot=obj, name=obj, default="")
    slot = getattr(obj, "slot", None)
    system = getattr(obj, "system", None)
    if slot or system:
        return part_icon_key(obj)
    item_type = (getattr(obj, "item_type", None) or "").strip().lower()
    if item_type == "vehicle":
        return "engine"
    if item_type in ("tool", "house"):
        return "cog"
    kind = None
    extra = None
    g = getattr(obj, "grocery", None)
    if g is not None:
        extra = getattr(g, "extra_data", None)
    if extra is None:
        extra = getattr(obj, "extra_data", None)
    if isinstance(extra, dict):
        kind = extra.get("kind")
    return part_icon_key(name=getattr(obj, "name", None), kind=kind, default="")
