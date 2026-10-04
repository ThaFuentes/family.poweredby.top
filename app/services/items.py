"""Items (inventory, vehicles, tools, house) shared by the item pages and Maya's API.

The form helpers that already live in ``app.routes.items`` (type rows, photo
saving, lookups) are imported lazily so the page module can import this one.
"""
from __future__ import annotations

from datetime import date, datetime

from app.builddb.builddb import db

ITEM_FIELDS = ("name", "category", "notes", "barcode", "tags", "linked_item_id")
TYPE_FORM_KEYS = {
    "grocery": ("quantity", "restock_threshold", "brand", "size", "unit", "default_location",
                "ingredients", "allergens", "serving_size", "packaging", "image_url", "auto_basket"),
    "tool": ("tool_type", "power_source", "oil_type", "fuel_type", "usage_notes",
             "maintenance_interval_hours", "oil_needs", "oil_capacity", "last_oil_date",
             "last_oil_hours", "oil_interval_hours", "oil_interval_months"),
    "vehicle": ("make", "model", "year", "vin", "plate", "color", "trim", "body_class", "drive_type",
                "fuel_type", "engine", "transmission", "doors", "manufacturer", "tire_size",
                "battery_type", "current_mileage", "manual_url", "oil_needs", "oil_capacity",
                "oil_type", "filter_type", "last_oil_change_date", "last_oil_change_mileage",
                "oil_interval_miles", "oil_interval_months"),
}


def _s(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else ""
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    return str(value)


def current_form(item) -> dict:
    """What the edit form would show now, so a partial update keeps the rest."""
    out = {
        "name": item.name or "",
        "category": item.category or "",
        "notes": item.notes or "",
        "barcode": item.barcode or "",
        "tags": ", ".join(item.tags) if isinstance(item.tags, list) else "",
        "linked_item_id": _s(item.linked_item_id),
    }
    row = {"grocery": item.grocery, "tool": item.tool, "vehicle": item.vehicle}.get(item.item_type)
    for key in TYPE_FORM_KEYS.get(item.item_type, ()):
        col = "type" if key == "tool_type" else key
        out[key] = _s(getattr(row, col, None)) if row is not None else ""
    return out


def merged_form(item, data: dict) -> dict:
    form = current_form(item)
    for key, val in (data or {}).items():
        if isinstance(val, list) and key == "tags":
            val = ", ".join(str(v) for v in val)
        form[key] = _s(val) if not isinstance(val, str) else val
    return form


def create_item(*, hid: int, user_id: int, form, photo=None, lookup=True):
    """(item, error, status). status: created | exists | forbidden | invalid."""
    from app.builddb.table_items import ITEM_TYPES, Item
    from app.routes.items import _attach_type_row, _enrich_from_lookups, can_create_type, save_item_photo
    from app.utils.household import scoped
    from app.utils.qr_labels import item_payload

    name = (form.get("name") or "").strip()
    item_type = (form.get("item_type") or "custom").strip().lower()
    barcode = (form.get("barcode") or "").strip() or None
    if not name:
        return None, "Name is required.", "invalid"
    if item_type not in ITEM_TYPES:
        item_type = "custom"
    if not can_create_type(item_type):
        return None, "This account cannot add that kind of item.", "forbidden"
    if barcode:
        exists = Item.query.filter_by(household_id=hid, barcode=barcode).first()
        if exists:
            return exists, "That barcode is already in this household.", "exists"
    item = Item(
        household_id=hid,
        name=name[:200],
        item_type=item_type,
        category=(form.get("category") or "").strip() or None,
        barcode=barcode,
        notes=(form.get("notes") or "").strip() or None,
        created_by=user_id,
    )
    tags = (form.get("tags") or "").strip()
    if tags:
        item.tags = [t.strip() for t in tags.split(",") if t.strip()]
    linked_raw = (form.get("linked_item_id") or "").strip()
    if linked_raw.isdigit():
        linked = scoped(Item).filter_by(id=int(linked_raw)).first()
        if linked:
            item.linked_item_id = linked.id
    db.session.add(item)
    db.session.flush()
    if not item.barcode:
        item.barcode = item_payload(hid, item.id)
    _attach_type_row(item, form)
    if lookup:
        _enrich_from_lookups(item)
    if photo is not None:
        save_item_photo(item, photo, form.get("caption"), user_id)
    return item, None, "created"


def edit_item(item, form, *, lookup=False) -> str | None:
    """Same as the item page's Save. None on success, else the message."""
    from app.builddb.table_items import Item
    from app.routes.items import _attach_type_row, _enrich_from_lookups
    from app.utils.household import scoped

    item.name = ((form.get("name") or item.name) or "").strip()[:200]
    item.category = (form.get("category") or "").strip() or None
    item.notes = (form.get("notes") or "").strip() or None
    barcode = (form.get("barcode") or "").strip() or None
    if barcode:
        clash = (
            Item.query.filter_by(household_id=item.household_id, barcode=barcode)
            .filter(Item.id != item.id)
            .first()
        )
        if clash:
            return "Barcode already used on another item."
        item.barcode = barcode
    tags = (form.get("tags") or "").strip()
    item.tags = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    linked_raw = (form.get("linked_item_id") or "").strip()
    if linked_raw.isdigit():
        linked = scoped(Item).filter_by(id=int(linked_raw)).first()
        item.linked_item_id = linked.id if linked else None
    elif linked_raw in ("", "0"):
        item.linked_item_id = None
    _attach_type_row(item, form)
    if lookup:
        _enrich_from_lookups(item)
    return None


def remove_item(item, *, actor):
    """Soft remove (removed_at) with a Put-back row on Happened."""
    from sqlalchemy.orm.attributes import flag_modified

    from app.utils.activity import record

    extra = dict(item.extra_data) if isinstance(item.extra_data, dict) else {}
    if item.barcode:
        extra["removed_barcode"] = item.barcode
        item.barcode = None
        item.extra_data = extra
        flag_modified(item, "extra_data")
    item.removed_at = datetime.utcnow()
    return record(
        action="item.remove",
        summary=f"{actor.name or actor.username} removed {item.name}",
        target_table="items",
        target_id=item.id,
        item_id=item.id,
        old_json={"name": item.name, "item_type": item.item_type},
        reversible=True,
    )


def restore_item(item, *, actor) -> tuple[bool, str]:
    """Same undo Happened uses; marks that Happened row as put back too."""
    from app.builddb.table_household_activity import HouseholdActivity
    from app.utils.activity import record, reverse_row

    row = (
        HouseholdActivity.query.filter_by(
            household_id=item.household_id, action="item.remove", target_id=item.id
        )
        .filter(HouseholdActivity.reversed_at.is_(None))
        .order_by(HouseholdActivity.id.desc())
        .first()
    )
    if row is not None:
        return reverse_row(row, by_id=actor.id)
    if item.removed_at is None:
        return False, "That item is not removed."
    item.removed_at = None
    extra = item.extra_data if isinstance(item.extra_data, dict) else {}
    old_code = extra.pop("removed_barcode", None)
    if old_code and not item.barcode:
        item.barcode = old_code
    record(action="item.restore", summary=f"{actor.name or actor.username} put back {item.name}",
           target_table="items", target_id=item.id, item_id=item.id, reversible=False)
    db.session.commit()
    return True, f"{item.name} is back in the house."


def stock_action(item, action, amount=1, *, user_id, place=None) -> dict:
    """The +/- / used / restock / need more / freezer buttons on an item."""
    from app.utils.scan import apply_grocery_stock, flag_need_more

    action = (str(action or "consume")).strip().lower()
    remember = True
    if action in ("plus", "add", "inc"):
        action, remember = "restock", False
    elif action in ("minus", "sub", "dec"):
        action, remember = "consume", False
    if action in ("need_more", "needs_more"):
        return flag_need_more(item.grocery, item, user_id)
    if action in ("freeze", "fridge", "freezer"):
        from app.utils.shelf_life import set_meat_storage

        frozen = action in ("freeze", "freezer")
        exp = set_meat_storage(item, item.grocery, frozen=frozen)
        return {
            "status": "ok",
            "message": f"{item.name} in the {'freezer' if frozen else 'fridge'}." + (f" Use by {exp}." if exp else ""),
        }
    return apply_grocery_stock(item.grocery, item, action, amount, user_id, remember=remember, place=place)


def set_reading(item, raw, *, user_id) -> tuple[bool, str]:
    """Odometer for a vehicle, hour meter for a tool. Writes the log row."""
    from app.utils.item_log import add_item_log
    from app.utils.scan import _dec

    text = str(raw if raw is not None else "").replace(",", "").strip()
    if item.item_type == "vehicle" and item.vehicle:
        try:
            miles = int(float(text))
        except Exception:
            return False, "Type the miles as a number."
        item.vehicle.current_mileage = miles
        add_item_log(item, kind="miles", user_id=user_id, reading=miles)
        return True, f"{item.name} is at {miles:,} miles."
    if item.item_type == "tool" and item.tool:
        try:
            hours = _dec(text, "0")
        except Exception:
            return False, "Type the hours as a number."
        item.tool.hours_used = hours
        add_item_log(item, kind="hours", user_id=user_id, reading=hours)
        return True, f"{item.name} is at {item.tool.hours_used} hours."
    return False, "Only vehicles and tools have a reading."


def retire_part(item, row, *, actor):
    from app.utils.activity import record

    row.is_current = False
    row.status = "retired"
    if not getattr(row, "removed_on", None):
        row.removed_on = date.today()
    return record(
        action="part.off",
        summary=f"{actor.name or actor.username} took {row.name} off {item.name}",
        target_table="vehicle_parts",
        target_id=row.id,
        item_id=item.id,
        old_json={"status": "installed", "is_current": True, "name": row.name, "system": row.system},
        new_json={"status": "retired"},
    )


def restore_part(item, row, *, actor) -> tuple[bool, str]:
    from app.builddb.table_household_activity import HouseholdActivity
    from app.utils.activity import reverse_row

    hist = (
        HouseholdActivity.query.filter_by(household_id=item.household_id, action="part.off", target_id=row.id)
        .filter(HouseholdActivity.reversed_at.is_(None))
        .order_by(HouseholdActivity.id.desc())
        .first()
    )
    if hist is not None:
        return reverse_row(hist, by_id=actor.id)
    if row.is_current:
        return False, "That part is already on."
    row.is_current = True
    row.status = "installed"
    db.session.commit()
    return True, f"{row.name} is back on."


def update_part(row, form):
    """Edit-part form. Only keys present in the form change (same as the page)."""
    from app.utils.vehicle_systems import parse_cost, parse_day

    name = (form.get("name") or "").strip()
    if name:
        row.name = name[:200]
    for key, cap in (("brand", 120), ("spec", 160), ("part_number", 80), ("model", 120), ("asset_id", 80)):
        if key in form:
            setattr(row, key, (form.get(key) or "").strip()[:cap] or None)
    if "serial_number" in form or "serial" in form:
        row.serial_number = (form.get("serial_number") or form.get("serial") or "").strip()[:120] or None
    if "part_notes" in form or "notes" in form:
        row.notes = (form.get("part_notes") or form.get("notes") or "").strip() or None
    if "source" in form:
        row.source = (form.get("source") or "").strip()[:200] or None
    if "cost" in form:
        row.cost = parse_cost(form.get("cost"))
    if "warranty_until" in form:
        row.warranty_until = parse_day(form.get("warranty_until"))
    if form.get("installed_on"):
        row.installed_on = parse_day(form.get("installed_on"))
    miles = (str(form.get("installed_mileage") or "")).replace(",", "").strip()
    if miles:
        try:
            row.installed_mileage = int(miles)
        except Exception:
            pass


def remove_photo(row, *, actor_id, via="ui"):
    from app.builddb.table_photo_notes import PhotoNote
    from app.utils import maya_store

    return maya_store.trash(
        hid=row.household_id,
        label=f"Photo #{row.id}",
        rows=[(PhotoNote, row)],
        files=[row.image_path] if row.image_path else [],
        actor_id=actor_id,
        via=via,
    )


def remove_log(row, *, actor_id, via="ui"):
    from app.builddb.table_item_logs import ItemLog
    from app.utils import maya_store

    return maya_store.trash(
        hid=row.household_id,
        label=f"Log: {row.title or row.kind} ({row.happened_on})",
        rows=[(ItemLog, row)],
        actor_id=actor_id,
        via=via,
    )
