"""Vehicle systems and part slots. Structured like a shop file, not a notepad."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation


def parse_cost(raw):
    s = str(raw or "").strip().replace("$", "").replace(",", "")
    if not s:
        return None
    try:
        d = Decimal(s)
    except (InvalidOperation, ValueError):
        return None
    if d < 0 or d > Decimal("99999999.99"):
        return None
    return d.quantize(Decimal("0.01"))


def parse_day(raw):
    from datetime import date

    if raw in (None, ""):
        return None
    if hasattr(raw, "isoformat") and not isinstance(raw, str):
        return raw
    s = str(raw).strip()[:10]
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except Exception:
        return None


SYSTEMS: tuple[tuple[str, str, str], ...] = (
    ("engine", "Engine", "Oil, filters, plugs, belts"),
    ("electrical", "Electrical", "Battery, alternator, starter, lights"),
    ("electronics", "Electronics", "Radio, cameras, computer, sensors"),
    ("exhaust", "Exhaust", "Muffler, catalytic, O2 sensors"),
    ("cooling", "Cooling", "Radiator, hoses, water pump"),
    ("fuel", "Fuel", "Filter, pump, injectors"),
    ("drivetrain", "Drivetrain", "Transmission, axles, differential"),
    ("brakes", "Brakes", "Pads, rotors, fluid"),
    ("steering", "Steering & suspension", "Shocks, tie rods, PS fluid"),
    ("tires", "Tires & wheels", "Size, brand, TPMS"),
    ("body", "Body", "Wipers, panels, glass, doors"),
    ("hvac", "Cabin / HVAC", "Cabin filter, A/C"),
    ("other", "Other", "Anything that does not fit above"),
)

# system -> ((slot_id, label, hint), ...)
SLOTS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "engine": (
        ("oil", "Engine oil", "5W-30, Dexos, quarts"),
        ("oil_filter", "Oil filter", "FL-820S, Wix, Fram"),
        ("air_filter", "Engine air filter", "Panel / cone"),
        ("spark_plugs", "Spark plugs", "Gap, heat range"),
        ("ignition_coils", "Ignition coils", ""),
        ("serpentine_belt", "Serpentine belt", "Length / ribs"),
        ("timing", "Timing belt / chain", ""),
        ("pcv", "PCV valve", ""),
    ),
    "electrical": (
        ("battery", "Battery", "Group size, CCA, AGM"),
        ("alternator", "Alternator", "Amps, connector"),
        ("starter", "Starter", ""),
        ("cables", "Cables / terminals", "Photo the connectors"),
        ("fuses", "Fuses / relays", ""),
        ("headlights", "Headlights", "H11, 9005…"),
        ("tail_lights", "Tail lights", ""),
    ),
    "electronics": (
        ("radio", "Radio / stereo", ""),
        ("infotainment", "Screen / infotainment", ""),
        ("cameras", "Cameras", "Backup, dash, trailer"),
        ("sensors", "Sensors", "Parking, ABS, TPMS module"),
        ("ecu", "Computer / module", ""),
        ("alarm", "Alarm / remote", ""),
        ("trailer_plug", "Trailer plug / wiring", ""),
    ),
    "exhaust": (
        ("manifold", "Exhaust manifold", ""),
        ("catalytic", "Catalytic converter", ""),
        ("o2_sensor", "O2 sensor", "Upstream / downstream"),
        ("muffler", "Muffler / resonator", ""),
        ("exhaust_pipe", "Pipes / hangers", ""),
    ),
    "cooling": (
        ("radiator", "Radiator", ""),
        ("coolant", "Coolant", "Color, mix, spec"),
        ("hoses", "Hoses", ""),
        ("water_pump", "Water pump", ""),
        ("thermostat", "Thermostat", ""),
        ("fan", "Fan / clutch", ""),
    ),
    "fuel": (
        ("fuel_filter", "Fuel filter", ""),
        ("fuel_pump", "Fuel pump", ""),
        ("injectors", "Injectors", ""),
        ("fuel_cap", "Cap / EVAP", ""),
    ),
    "drivetrain": (
        ("trans_fluid", "Transmission fluid", "Mercon, Dexron, quarts"),
        ("trans_filter", "Transmission filter", ""),
        ("transfer_case", "Transfer case fluid", ""),
        ("diff_front", "Front differential", ""),
        ("diff_rear", "Rear differential", ""),
        ("cv_axle", "CV axle", "Left / right"),
        ("clutch", "Clutch", ""),
    ),
    "brakes": (
        ("pads_front", "Front pads", "Ceramic / semi-met"),
        ("pads_rear", "Rear pads", ""),
        ("rotors_front", "Front rotors", ""),
        ("rotors_rear", "Rear rotors", ""),
        ("brake_fluid", "Brake fluid", "DOT 3 / 4"),
        ("calipers", "Calipers", ""),
    ),
    "steering": (
        ("ps_fluid", "Power steering fluid", ""),
        ("shocks_front", "Front shocks / struts", ""),
        ("shocks_rear", "Rear shocks / struts", ""),
        ("tie_rods", "Tie rods", ""),
        ("ball_joints", "Ball joints", ""),
        ("control_arms", "Control arms", ""),
    ),
    "tires": (
        ("tires", "Tires", "275/65R18, load, brand"),
        ("spare", "Spare", ""),
        ("tpms", "TPMS", ""),
        ("alignment", "Alignment", "Last date"),
        ("wheels", "Wheels / lug nuts", "Torque"),
    ),
    "body": (
        ("wipers", "Wiper blades", "Driver / passenger size"),
        ("wiper_fluid", "Washer fluid", ""),
        ("mirrors", "Mirrors", ""),
        ("glass", "Glass / windshield", ""),
        ("paint", "Paint / panels", "Color code"),
        ("locks", "Locks / latches", ""),
        ("bumper", "Bumper", ""),
        ("doors", "Doors / handles", ""),
        ("tailgate", "Tailgate / trunk", ""),
        ("bed", "Bed / liner", ""),
        ("interior", "Interior / seats", ""),
        ("grill", "Grill / trim", ""),
    ),
    "hvac": (
        ("cabin_filter", "Cabin filter", ""),
        ("ac_compressor", "A/C compressor", ""),
        ("ac_refrigerant", "Refrigerant", "R-134a / 1234yf"),
        ("heater_core", "Heater core", ""),
    ),
    "other": (("misc", "Other part", "Name it"),),
}

KIND_SLOT = {
    "car_battery": ("electrical", "battery"),
    "motor_oil": ("engine", "oil"),
    "filter": ("engine", "oil_filter"),
    "aa_battery": ("electrical", "battery"),
}

_SLOT_HINTS = (
    ("alternator", "electrical", "alternator"),
    ("starter", "electrical", "starter"),
    ("cabin filter", "hvac", "cabin_filter"),
    ("cabin air", "hvac", "cabin_filter"),
    ("air filter", "engine", "air_filter"),
    ("oil filter", "engine", "oil_filter"),
    ("fuel filter", "fuel", "fuel_filter"),
    ("spark plug", "engine", "spark_plugs"),
    ("wiper", "body", "wipers"),
    ("brake pad", "brakes", "pads_front"),
    ("rotor", "brakes", "rotors_front"),
    ("coolant", "cooling", "coolant"),
    ("antifreeze", "cooling", "coolant"),
    ("tire", "tires", "tires"),
    ("muffler", "exhaust", "muffler"),
    ("catalytic", "exhaust", "catalytic"),
    ("o2 sensor", "exhaust", "o2_sensor"),
    ("oxygen sensor", "exhaust", "o2_sensor"),
    ("serpentine", "engine", "serpentine_belt"),
    ("radiator", "cooling", "radiator"),
    ("thermostat", "cooling", "thermostat"),
    ("water pump", "cooling", "water_pump"),
    ("headlight", "electrical", "headlights"),
    ("radio", "electronics", "radio"),
    ("stereo", "electronics", "radio"),
    ("backup cam", "electronics", "cameras"),
    ("camera", "electronics", "cameras"),
    ("ecu", "electronics", "ecu"),
    ("cv axle", "drivetrain", "cv_axle"),
    ("transmission fluid", "drivetrain", "trans_fluid"),
    ("shock", "steering", "shocks_front"),
    ("strut", "steering", "shocks_front"),
)


def system_ids() -> tuple[str, ...]:
    return tuple(s[0] for s in SYSTEMS)


def system_label(system_id: str) -> str:
    for sid, label, _hint in SYSTEMS:
        if sid == system_id:
            return label
    return (system_id or "Other").replace("_", " ").title()


def slot_label(system_id: str, slot_id: str, slots=None) -> str:
    slot_map = slots or SLOTS
    for sid, label, _hint in slot_map.get(system_id) or ():
        if sid == slot_id:
            return label
    return (slot_id or "Part").replace("_", " ").title()


def slot_hint(system_id: str, slot_id: str) -> str:
    for sid, _label, hint in SLOTS.get(system_id) or ():
        if sid == slot_id:
            return hint
    return ""


def valid_system(system_id: str, slots=None) -> str:
    slot_map = slots or SLOTS
    s = (system_id or "").strip().lower()
    return s if s in slot_map else "other"


def valid_slot(system_id: str, slot_id: str, slots=None) -> str:
    slot_map = slots or SLOTS
    system_id = valid_system(system_id, slot_map)
    s = (slot_id or "").strip().lower()
    ordered = [row[0] for row in slot_map.get(system_id) or ()]
    if s in ordered:
        return s
    return ordered[0] if ordered else "misc"


def guess_slot(kind: str | None = None, name: str = "", category: str = "") -> tuple[str, str]:
    kind = (kind or "").strip().lower()
    if kind in KIND_SLOT:
        mapped = KIND_SLOT[kind]
        hay = f"{name} {category}".lower()
        if kind == "filter":
            for needle, sys_id, slot_id in _SLOT_HINTS:
                if needle in hay:
                    return sys_id, slot_id
        return mapped
    hay = f"{kind} {name} {category}".lower()
    for needle, sys_id, slot_id in _SLOT_HINTS:
        if needle in hay:
            return sys_id, slot_id
    if "battery" in hay:
        return "electrical", "battery"
    if "oil" in hay:
        return "engine", "oil"
    return "other", "misc"


def systems_payload(systems=None, slots=None) -> list[dict]:
    catalog = systems or SYSTEMS
    slot_map = slots or SLOTS
    out = []
    for sid, label, hint in catalog:
        out.append(
            {
                "id": sid,
                "label": label,
                "hint": hint,
                "slots": [
                    {"id": slot, "label": slabel, "hint": shint}
                    for slot, slabel, shint in slot_map.get(sid) or ()
                ],
            }
        )
    return out


def install_part(
    *,
    hid: int,
    vehicle_item_id: int,
    user_id=None,
    system: str,
    slot: str,
    name: str,
    brand: str | None = None,
    spec: str | None = None,
    part_number: str | None = None,
    status: str = "installed",
    installed_on=None,
    installed_mileage=None,
    notes: str | None = None,
    source: str | None = None,
    cost=None,
    warranty_until=None,
    catalog_item_id=None,
    replace_current: bool = True,
    catalog_slots=None,
):
    from datetime import date

    from app.builddb.builddb import db
    from app.builddb.table_vehicle_parts import VehiclePart

    slot_map = catalog_slots or SLOTS
    system = valid_system(system, slot_map)
    slot = valid_slot(system, slot, slot_map)
    name = (name or "").strip() or slot_label(system, slot, slot_map)
    status = (status or "installed").strip().lower()
    if status not in ("installed", "spare", "retired"):
        status = "installed"
    replaced_id = None
    if replace_current and status == "installed":
        current = (
            VehiclePart.query.filter_by(
                household_id=hid,
                vehicle_item_id=vehicle_item_id,
                system=system,
                slot=slot,
                is_current=True,
            )
            .filter(VehiclePart.status != "retired")
            .all()
        )
        for old in current:
            old.is_current = False
            old.status = "retired"
            replaced_id = old.id
    miles = None
    if installed_mileage not in (None, ""):
        try:
            miles = int(str(installed_mileage).replace(",", "").strip())
        except Exception:
            miles = None
    when = parse_day(installed_on)
    if when is None and status == "installed":
        when = date.today()
    row = VehiclePart(
        household_id=hid,
        vehicle_item_id=vehicle_item_id,
        catalog_item_id=catalog_item_id,
        system=system,
        slot=slot,
        name=name[:200],
        brand=(brand or "").strip()[:120] or None,
        spec=(spec or "").strip()[:160] or None,
        part_number=(part_number or "").strip()[:80] or None,
        status=status,
        is_current=status != "retired",
        installed_on=when,
        installed_mileage=miles,
        notes=(notes or "").strip() or None,
        source=(source or "").strip()[:200] or None,
        cost=parse_cost(cost),
        warranty_until=parse_day(warranty_until),
        replaced_id=replaced_id,
        created_by=user_id,
    )
    db.session.add(row)
    db.session.flush()
    return row


def attach_scanned_part(
    *,
    hid: int,
    user_id,
    vehicle_item_id: int,
    catalog_item,
    kind: str | None,
    name: str,
    brand: str | None = None,
    status: str = "installed",
):
    from app.builddb.table_items import Item

    vehicle = Item.query.filter_by(id=vehicle_item_id, household_id=hid).first()
    if vehicle is None or vehicle.item_type not in ("vehicle", "house", "tool"):
        return None
    system, slot = guess_slot(kind, name=name, category=getattr(catalog_item, "category", "") or "")
    catalog_slots = None
    if vehicle.item_type == "house":
        from app.utils.house_systems import HOUSE_SLOTS

        catalog_slots = HOUSE_SLOTS
        if (kind or "") in ("filter", "hvac_filter") or "filter" in (name or "").lower():
            system, slot = "hvac", "filter"
    spec = None
    if catalog_item is not None and getattr(catalog_item, "grocery", None):
        spec = catalog_item.grocery.size
    return install_part(
        hid=hid,
        vehicle_item_id=vehicle.id,
        user_id=user_id,
        system=system,
        slot=slot,
        name=name,
        brand=brand,
        spec=spec,
        catalog_item_id=getattr(catalog_item, "id", None),
        status=status or "installed",
        catalog_slots=catalog_slots,
        replace_current=(status or "installed") == "installed",
    )


def seed_from_vehicle_fields(vehicle_item) -> int:
    """Copy oil/battery/filter/tires from the old single fields into parts, once."""
    v = getattr(vehicle_item, "vehicle", None)
    if v is None:
        return 0
    from app.builddb.table_vehicle_parts import VehiclePart

    hid = vehicle_item.household_id
    existing = VehiclePart.query.filter_by(household_id=hid, vehicle_item_id=vehicle_item.id).count()
    if existing:
        return 0
    seeds = [
        ("engine", "oil", v.oil_type, "Engine oil"),
        ("engine", "oil_filter", v.filter_type, "Oil filter"),
        ("electrical", "battery", v.battery_type, "Battery"),
        ("tires", "tires", v.tire_size, "Tires"),
    ]
    n = 0
    for system, slot, value, label in seeds:
        val = (value or "").strip()
        if not val:
            continue
        install_part(
            hid=hid,
            vehicle_item_id=vehicle_item.id,
            system=system,
            slot=slot,
            name=f"{label} — {val}",
            spec=val,
            status="installed",
        )
        n += 1
    return n


def group_parts(parts, systems=None, slots=None) -> list[dict]:
    """parts: iterable of VehiclePart. Current first, then history."""
    catalog = systems or SYSTEMS
    slot_map = slots or SLOTS
    by_sys: dict[str, list] = {sid: [] for sid, _l, _h in catalog}
    for p in parts:
        sid = valid_system(getattr(p, "system", None) or "other", slot_map)
        by_sys.setdefault(sid, []).append(p)
    grouped = []
    for sid, label, hint in catalog:
        rows = by_sys.get(sid) or []
        current = [p for p in rows if getattr(p, "is_current", False) and (p.status or "installed") != "retired"]
        history = [p for p in rows if p not in current]
        filled_slots = {p.slot for p in current}
        empty = [
            {"id": slot, "label": slabel, "hint": shint}
            for slot, slabel, shint in slot_map.get(sid) or ()
            if slot not in filled_slots
        ]
        grouped.append(
            {
                "id": sid,
                "label": label,
                "hint": hint,
                "current": current,
                "history": history,
                "empty_slots": empty,
                "count": len(current),
            }
        )
    return grouped
