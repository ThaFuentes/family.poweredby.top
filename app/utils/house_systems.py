"""House systems — same shop-file pattern as the vehicle, for the building."""
from __future__ import annotations

from app.utils.vehicle_systems import group_parts, install_part, systems_payload

HOUSE_SYSTEMS: tuple[tuple[str, str, str], ...] = (
    ("hvac", "HVAC", "Filter, furnace, A/C"),
    ("water", "Water", "Heater, softener, whole-house filter"),
    ("safety", "Safety", "Smoke, CO, extinguisher"),
    ("electrical", "Electrical", "Panel, generator, backup"),
    ("plumbing", "Plumbing", "Sink, faucet, shutoff, sump"),
    ("appliances", "Kitchen & laundry", "Fridge, range, microwave, washer"),
    ("electronics", "Electronics", "TVs, computers, speakers, printers"),
    ("fitness", "Fitness", "Treadmill, bench, weights"),
    ("pool", "Pool", "Pump, filter, chemicals"),
    ("coop", "Coop & feed", "Coop, feed, hay, waterer"),
    ("other", "Other", "Anything else in the house"),
)

HOUSE_SLOTS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "hvac": (
        ("filter", "HVAC filter", "Size on the frame — 16x25x1"),
        ("furnace", "Furnace", "Model / serial"),
        ("ac", "A/C outdoor unit", "Photo the data plate"),
        ("thermostat", "Thermostat", ""),
        ("humidifier", "Humidifier / dehumidifier", ""),
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
        ("safe", "Safe / lockbox", ""),
    ),
    "electrical": (
        ("panel", "Breaker panel", "Photo the legend"),
        ("generator", "Generator", "Fuel, oil"),
        ("battery_backup", "Battery backup", ""),
        ("solar", "Solar / inverter", ""),
    ),
    "plumbing": (
        ("shutoff", "Main shutoff", "Where it is"),
        ("sink", "Kitchen sink", "Basin / bowl"),
        ("faucet", "Kitchen faucet", "Model / finish"),
        ("sprayer", "Sprayer / hose", ""),
        ("supply_lines", "Supply lines", ""),
        ("ptrap", "P-trap / drain", ""),
        ("undersink_filter", "Under-sink filter", ""),
        ("sump", "Sump pump", ""),
        ("disposal", "Disposal", ""),
        ("toilet", "Toilet", ""),
    ),
    "appliances": (
        ("fridge", "Fridge", "Model / serial, filter"),
        ("freezer", "Freezer", ""),
        ("range", "Range / stove", "Gas / electric / induction"),
        ("cooktop", "Cooktop", ""),
        ("oven", "Wall oven", ""),
        ("microwave", "Microwave", ""),
        ("air_fryer", "Air fryer", ""),
        ("dishwasher", "Dishwasher", ""),
        ("hood", "Range hood", ""),
        ("coffee", "Coffee maker", ""),
        ("toaster", "Toaster / toaster oven", ""),
        ("washer", "Washer", ""),
        ("dryer", "Dryer", "Vent last cleaned"),
        ("iron", "Iron / steamer", ""),
    ),
    "electronics": (
        ("tv", "TV", "Model / serial / HDMI"),
        ("monitor", "Monitor", ""),
        ("laptop", "Laptop", ""),
        ("desktop", "Desktop / tower", ""),
        ("tablet", "Tablet", ""),
        ("phone", "Phone", ""),
        ("speaker", "Speaker", ""),
        ("soundbar", "Soundbar / receiver", ""),
        ("headphones", "Headphones", ""),
        ("console", "Game console", ""),
        ("router", "Router / mesh", ""),
        ("modem", "Modem", ""),
        ("printer", "Printer / scanner", ""),
        ("threed_printer", "3D printer", ""),
        ("camera", "Camera / webcam", ""),
        ("streamer", "Streamer / box", "Roku, Apple TV, Fire"),
        ("server", "NAS / server", ""),
    ),
    "fitness": (
        ("treadmill", "Treadmill", ""),
        ("exercise_bike", "Exercise bike", ""),
        ("bench", "Weight bench", ""),
        ("weights", "Weights / dumbbells", ""),
        ("rack", "Rack / squat stand", ""),
        ("rower", "Rower", ""),
        ("other_gym", "Other gym", ""),
    ),
    "pool": (
        ("pump", "Pool pump", "Model / serial"),
        ("filter", "Pool filter", "Cartridge / sand / DE"),
        ("heater", "Pool heater", ""),
        ("salt_cell", "Salt cell", ""),
        ("skimmer", "Skimmer / baskets", ""),
        ("cover", "Cover / reel", ""),
        ("cleaner", "Cleaner / robot", ""),
        ("chlorine", "Chlorine / tablets", "Consumable — scan the jug"),
        ("shock", "Shock", ""),
        ("algaecide", "Algaecide", ""),
        ("ph", "pH / alkalinity", "Acid, soda ash, bicarb"),
        ("stabilizer", "Stabilizer / CYA", ""),
        ("salt", "Pool salt", ""),
        ("test_kit", "Test kit / strips", ""),
        ("other_chem", "Other chemical", ""),
    ),
    "coop": (
        ("coop", "Coop / run", ""),
        ("feeder", "Feeder", ""),
        ("waterer", "Waterer", ""),
        ("heat_lamp", "Heat lamp / brooder", ""),
        ("nesting", "Nesting boxes", ""),
        ("fencing", "Fencing / netting", ""),
        ("feed", "Feed", "Layer, starter, scratch — scan the bag"),
        ("hay", "Hay / straw", ""),
        ("bedding", "Bedding / shavings", ""),
        ("grit", "Grit / oyster shell", ""),
        ("other_coop", "Other coop gear", ""),
    ),
    "other": (("misc", "Other", "Name it"),),
}

_HOUSE_HINTS = (
    ("kitchen faucet", "plumbing", "faucet"),
    ("kitchen sink", "plumbing", "sink"),
    ("p-trap", "plumbing", "ptrap"),
    ("ptrap", "plumbing", "ptrap"),
    ("supply line", "plumbing", "supply_lines"),
    ("sprayer", "plumbing", "sprayer"),
    ("under-sink", "plumbing", "undersink_filter"),
    ("under sink", "plumbing", "undersink_filter"),
    ("faucet", "plumbing", "faucet"),
    ("pool pump", "pool", "pump"),
    ("pool filter", "pool", "filter"),
    ("pool heater", "pool", "heater"),
    ("salt cell", "pool", "salt_cell"),
    ("pool salt", "pool", "salt"),
    ("pool shock", "pool", "shock"),
    ("chlorine", "pool", "chlorine"),
    ("algaecide", "pool", "algaecide"),
    ("muriatic", "pool", "ph"),
    ("cyanuric", "pool", "stabilizer"),
    ("test strip", "pool", "test_kit"),
    ("pool", "pool", "other_chem"),
    ("chicken feed", "coop", "feed"),
    ("layer feed", "coop", "feed"),
    ("scratch", "coop", "feed"),
    ("oyster shell", "coop", "grit"),
    ("heat lamp", "coop", "heat_lamp"),
    ("brooder", "coop", "heat_lamp"),
    ("nesting", "coop", "nesting"),
    ("waterer", "coop", "waterer"),
    ("feeder", "coop", "feeder"),
    ("shavings", "coop", "bedding"),
    ("pine bedding", "coop", "bedding"),
    ("chicken", "coop", "other_coop"),
    ("coop", "coop", "coop"),
    ("hay", "coop", "hay"),
    ("straw", "coop", "hay"),
    ("air fryer", "appliances", "air_fryer"),
    ("airfryer", "appliances", "air_fryer"),
    ("microwave", "appliances", "microwave"),
    ("dishwasher", "appliances", "dishwasher"),
    ("washing machine", "appliances", "washer"),
    ("washer", "appliances", "washer"),
    ("dryer", "appliances", "dryer"),
    ("refrigerator", "appliances", "fridge"),
    ("fridge", "appliances", "fridge"),
    ("freezer", "appliances", "freezer"),
    ("range", "appliances", "range"),
    ("stove", "appliances", "range"),
    ("cooktop", "appliances", "cooktop"),
    ("oven", "appliances", "oven"),
    ("coffee", "appliances", "coffee"),
    ("toaster", "appliances", "toaster"),
    ("3d printer", "electronics", "threed_printer"),
    ("3-d printer", "electronics", "threed_printer"),
    ("laptop", "electronics", "laptop"),
    ("notebook", "electronics", "laptop"),
    ("desktop", "electronics", "desktop"),
    ("imac", "electronics", "desktop"),
    ("mac mini", "electronics", "desktop"),
    ("monitor", "electronics", "monitor"),
    ("display", "electronics", "monitor"),
    ("television", "electronics", "tv"),
    ("tv ", "electronics", "tv"),
    (" tv", "electronics", "tv"),
    ("soundbar", "electronics", "soundbar"),
    ("speaker", "electronics", "speaker"),
    ("headphone", "electronics", "headphones"),
    ("playstation", "electronics", "console"),
    ("xbox", "electronics", "console"),
    ("nintendo", "electronics", "console"),
    ("switch", "electronics", "console"),
    ("router", "electronics", "router"),
    ("mesh", "electronics", "router"),
    ("modem", "electronics", "modem"),
    ("printer", "electronics", "printer"),
    ("tablet", "electronics", "tablet"),
    ("ipad", "electronics", "tablet"),
    ("iphone", "electronics", "phone"),
    ("camera", "electronics", "camera"),
    ("roku", "electronics", "streamer"),
    ("fire tv", "electronics", "streamer"),
    ("apple tv", "electronics", "streamer"),
    ("nas", "electronics", "server"),
    ("treadmill", "fitness", "treadmill"),
    ("exercise bike", "fitness", "exercise_bike"),
    ("peloton", "fitness", "exercise_bike"),
    ("weight bench", "fitness", "bench"),
    ("bench", "fitness", "bench"),
    ("dumbbell", "fitness", "weights"),
    ("kettlebell", "fitness", "weights"),
    ("squat rack", "fitness", "rack"),
    ("rower", "fitness", "rower"),
    ("smoke", "safety", "smoke"),
    ("extinguisher", "safety", "extinguisher"),
    ("water heater", "water", "heater"),
    ("furnace", "hvac", "furnace"),
    ("thermostat", "hvac", "thermostat"),
)


def guess_house_slot(name: str = "", kind: str = "") -> tuple[str, str]:
    blob = f" {(name or '')} {(kind or '')} ".lower()
    for needle, system, slot in _HOUSE_HINTS:
        if needle in blob:
            return system, slot
    if "tv" in blob:
        return "electronics", "tv"
    return "other", "misc"


def house_system_label(system_id: str) -> str:
    for sid, label, _hint in HOUSE_SYSTEMS:
        if sid == system_id:
            return label
    return (system_id or "Other").replace("_", " ").title()


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
        .filter(Item.removed_at.is_(None))
        .order_by(Item.id.asc())
        .first()
    )
    if row:
        return row, False
    row = (
        Item.query.filter_by(household_id=household_id, item_type="house")
        .order_by(Item.id.asc())
        .first()
    )
    if row:
        row.removed_at = None
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
