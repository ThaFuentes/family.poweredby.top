"""Put a recorded household change back. No hard delete, no vault writes.

The activity row carries an `undo` tag the server wrote. Happened and Maya's
activity undo both call `undo_recorded`. A tag without a handler stays
irreversible, so a row is never marked reversible unless this file can
actually restore it.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.builddb.builddb import db

HIDE_ITEM = {"undo": "hide_item"}
RETIRE_PART = {"undo": "retire_part"}

_ITEM_FIELDS = ("name", "category", "notes")
_GROCERY_FIELDS = (
    "quantity",
    "restock_threshold",
    "needs_restock",
    "is_in_stock",
    "default_location",
    "brand",
    "size",
    "unit",
)
_VEHICLE_FIELDS = (
    "make", "model", "year", "vin", "plate", "color", "trim", "body_class",
    "drive_type", "fuel_type", "engine", "transmission", "oil_type", "oil_needs",
    "oil_capacity", "filter_type", "tire_size", "battery_type", "current_mileage",
    "last_oil_change_mileage", "oil_interval_miles", "oil_interval_months",
    "last_oil_change_date", "next_oil_due_date", "next_oil_due_mileage",
)
_TOOL_FIELDS = (
    "type", "model", "serial_number", "asset_id", "power_source", "oil_needs",
    "oil_capacity", "oil_type", "fuel_type", "hours_used", "last_oil_date",
    "last_oil_hours", "oil_interval_hours", "oil_interval_months",
    "next_oil_due_date", "next_oil_due_hours",
)
_NOTE_FIELDS = ("title", "body", "visibility", "item_id")
_REMINDER_FIELDS = ("title", "type", "notes", "linked_item_id", "recurrence", "due_at", "status")
_CASE_FIELDS = ("title", "status", "summary")
_RECORD_FIELDS = (
    "title", "kind", "status", "agency", "case_number", "location", "body",
    "outcome", "issued_on", "due_on", "amount", "case_id",
)
_BASKET_FIELDS = ("status", "name", "item_id", "completed_at", "note", "quantity_needed")
_LOG_FIELDS = ("reading", "notes", "title", "extra_data", "happened_on")
_PART_FIELDS = (
    "name", "brand", "spec", "part_number", "model", "status", "is_current",
    "notes", "system", "slot",
)
_DATE_FIELDS = frozenset({
    "last_oil_change_date", "next_oil_due_date", "last_oil_date",
    "next_oil_due_date", "issued_on", "due_on", "happened_on", "installed_on",
})
_DT_FIELDS = frozenset({"due_at", "completed_at"})
_DEC_FIELDS = frozenset({
    "quantity", "restock_threshold", "hours_used", "amount", "reading",
    "quantity_needed", "cost",
})
_INT_FIELDS = frozenset({
    "year", "current_mileage", "last_oil_change_mileage", "oil_interval_miles",
    "oil_interval_months", "next_oil_due_mileage", "last_oil_hours",
    "oil_interval_hours", "next_oil_due_hours", "item_id", "linked_item_id",
    "case_id", "installed_mileage",
})
_BOOL_FIELDS = frozenset({"needs_restock", "is_in_stock", "is_current"})


def _plain(value):
    if value is None or isinstance(value, (int, float, str, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k)[:80]: _plain(v) for k, v in list(value.items())[:40]}
    if isinstance(value, list):
        return [_plain(v) for v in value[:40]]
    return str(value)[:500]


def _copy_fields(obj, names) -> dict | None:
    if obj is None:
        return None
    out = {}
    for name in names:
        if hasattr(obj, name):
            out[name] = _plain(getattr(obj, name))
    return out


def snap_item(item) -> dict | None:
    data = _copy_fields(item, _ITEM_FIELDS)
    if data is None:
        return None
    tags = getattr(item, "tags", None)
    if isinstance(tags, list):
        data["tags"] = [str(t)[:40] for t in tags[:20]]
    return data


def snap_grocery(row) -> dict | None:
    data = _copy_fields(row, _GROCERY_FIELDS)
    if data is None:
        return None
    extra = getattr(row, "extra_data", None)
    if isinstance(extra, dict):
        data["extra_data"] = _plain(extra)
    return data


def snap_vehicle(row) -> dict | None:
    return _copy_fields(row, _VEHICLE_FIELDS)


def snap_tool(row) -> dict | None:
    return _copy_fields(row, _TOOL_FIELDS)


def snap_note(row) -> dict | None:
    return _copy_fields(row, _NOTE_FIELDS)


def snap_reminder(row) -> dict | None:
    return _copy_fields(row, _REMINDER_FIELDS)


def snap_case(row) -> dict | None:
    return _copy_fields(row, _CASE_FIELDS)


def snap_record(row) -> dict | None:
    return _copy_fields(row, _RECORD_FIELDS)


def snap_basket(row) -> dict | None:
    return _copy_fields(row, _BASKET_FIELDS)


def snap_log(row) -> dict | None:
    return _copy_fields(row, _LOG_FIELDS)


def snap_part(row) -> dict | None:
    return _copy_fields(row, _PART_FIELDS)


def oil_snap(host) -> dict | None:
    if host is None:
        return None
    names = _VEHICLE_FIELDS if hasattr(host, "current_mileage") else _TOOL_FIELDS
    data = _copy_fields(host, names) or {}
    from app.utils.oil import get_fluids

    data["fluids"] = get_fluids(host)
    return data


def living_snap(item) -> dict | None:
    """Odometer, hours, and oil on the vehicle or tool before a log changes them."""
    if item is None:
        return None
    if getattr(item, "vehicle", None) is not None:
        return {"vehicle": oil_snap(item.vehicle)}
    if getattr(item, "tool", None) is not None:
        return {"tool": oil_snap(item.tool)}
    return None


def fields_undo(**sections) -> dict:
    clean = {key: value for key, value in sections.items() if value}
    clean["undo"] = "fields"
    return clean


def trash_undo(*ids: int, maintenance_id: int | None = None, living: dict | None = None) -> dict:
    payload = {"undo": "trash", "ids": [int(i) for i in ids if i]}
    if maintenance_id:
        payload["maintenance_id"] = int(maintenance_id)
    if living:
        payload["living"] = living
    return payload


def _same_house(obj, hid: int) -> bool:
    if obj is None:
        return False
    other = getattr(obj, "household_id", None)
    if other is None:
        return False
    try:
        return int(other) == int(hid)
    except (TypeError, ValueError):
        return False


def _model(table: str):
    if table == "items":
        from app.builddb.table_items import Item
        return Item
    if table == "grocery_list":
        from app.builddb.table_grocery_list import GroceryListEntry
        return GroceryListEntry
    if table == "reminders":
        from app.builddb.table_reminders import Reminder
        return Reminder
    if table == "legal_cases":
        from app.builddb.table_legal_cases import LegalCase
        return LegalCase
    if table == "legal_records":
        from app.builddb.table_legal_records import LegalRecord
        return LegalRecord
    if table == "vehicle_parts":
        from app.builddb.table_vehicle_parts import VehiclePart
        return VehiclePart
    if table == "notes":
        from app.builddb.table_notes import Note
        return Note
    if table == "item_logs":
        from app.builddb.table_item_logs import ItemLog
        return ItemLog
    if table == "note_files":
        from app.builddb.table_note_files import NoteFile
        return NoteFile
    if table == "legal_followups":
        from app.builddb.table_legal_followups import LegalFollowup
        return LegalFollowup
    if table == "legal_files":
        from app.builddb.table_legal_files import LegalFile
        return LegalFile
    if table == "photo_notes":
        from app.builddb.table_photo_notes import PhotoNote
        return PhotoNote
    if table == "maintenance_records":
        from app.builddb.table_maintenance_records import MaintenanceRecord
        return MaintenanceRecord
    return None


def _load(table: str, row_id, hid: int):
    model = _model(table)
    if model is None or not row_id:
        return None
    obj = model.query.filter_by(id=int(row_id)).first()
    if not _same_house(obj, hid):
        return None
    return obj


def _as_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _as_dt(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).replace("T", " ")[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _as_dec(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _as_int(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce(name: str, value):
    if name in _DATE_FIELDS:
        return _as_date(value)
    if name in _DT_FIELDS:
        return _as_dt(value)
    if name in _DEC_FIELDS:
        return _as_dec(value)
    if name in _INT_FIELDS:
        return _as_int(value)
    if name in _BOOL_FIELDS:
        return bool(value)
    if value is None:
        return None
    return value


def _apply(obj, data: dict, allow: tuple[str, ...]) -> None:
    if obj is None or not isinstance(data, dict):
        return
    allowed = set(allow)
    for key, value in data.items():
        if key not in allowed or not hasattr(obj, key):
            continue
        setattr(obj, key, _coerce(key, value))


def _restore_fluids(host, fluids) -> None:
    if host is None:
        return
    from app.utils.oil import FLUID_LABELS

    extra = dict(host.extra_data) if isinstance(host.extra_data, dict) else {}
    clean = {}
    if isinstance(fluids, dict):
        for key, value in fluids.items():
            if key in FLUID_LABELS and str(value or "").strip():
                clean[str(key)] = str(value).strip()[:200]
    extra["fluids"] = clean
    host.extra_data = extra


def _restore_oil(host, data: dict) -> None:
    if host is None or not isinstance(data, dict):
        return
    names = _VEHICLE_FIELDS if hasattr(host, "current_mileage") else _TOOL_FIELDS
    _apply(host, data, names)
    if "fluids" in data:
        _restore_fluids(host, data.get("fluids"))


def _hide_item(row) -> tuple[bool, str]:
    from sqlalchemy.orm.attributes import flag_modified

    item = _load("items", row.target_id or row.item_id, row.household_id)
    if item is None:
        return False, "Can't find that item."
    if item.removed_at is None:
        extra = dict(item.extra_data) if isinstance(item.extra_data, dict) else {}
        if item.barcode:
            extra["removed_barcode"] = item.barcode
            item.barcode = None
            item.extra_data = extra
            flag_modified(item, "extra_data")
        item.removed_at = datetime.utcnow()
    return True, f"{item.name} is put away."


def _retire_part(row) -> tuple[bool, str]:
    part = _load("vehicle_parts", row.target_id, row.household_id)
    if part is None:
        return False, "Can't find that part."
    part.is_current = False
    part.status = "retired"
    return True, f"{part.name} is off again."


def _status(row, spec: dict) -> tuple[bool, str]:
    table = (row.target_table or "").strip()
    allowed = {
        "grocery_list": {"open", "done"},
        "reminders": {"open", "done"},
        "legal_cases": {"open", "closed"},
        "legal_records": {"open", "paid", "contested", "appealed", "dismissed", "closed"},
    }.get(table)
    status = (spec.get("status") or "").strip().lower()
    if allowed is None or status not in allowed:
        return False, "That one can't be undone."
    obj = _load(table, row.target_id, row.household_id)
    if obj is None:
        return False, "Can't find that anymore."
    obj.status = status
    if table == "grocery_list" and "completed_at" in spec:
        raw = spec.get("completed_at")
        obj.completed_at = datetime.utcnow() if raw == "now" else _as_dt(raw)
    name = getattr(obj, "name", None) or getattr(obj, "title", None) or "That"
    return True, f"{name} is back to {status}."


def _restore_fields(row, spec: dict) -> tuple[bool, str]:
    hid = row.household_id
    item = _load("items", row.item_id or row.target_id, hid) if (row.target_table == "items" or row.item_id) else None
    if isinstance(spec.get("item"), dict):
        if item is None and row.target_table == "items":
            return False, "Can't find that item."
        if item is not None:
            _apply(item, spec["item"], _ITEM_FIELDS)
            tags = spec["item"].get("tags") if "tags" in spec["item"] else None
            if isinstance(tags, list):
                item.tags = [str(t)[:40] for t in tags[:20] if str(t).strip()]
    if isinstance(spec.get("grocery"), dict) and item is not None and item.grocery is not None:
        _apply(item.grocery, spec["grocery"], _GROCERY_FIELDS)
        if isinstance(spec["grocery"].get("extra_data"), dict):
            item.grocery.extra_data = spec["grocery"]["extra_data"]
    if isinstance(spec.get("vehicle"), dict) and item is not None and item.vehicle is not None:
        _apply(item.vehicle, spec["vehicle"], _VEHICLE_FIELDS)
        if "fluids" in spec["vehicle"]:
            _restore_fluids(item.vehicle, spec["vehicle"].get("fluids"))
    if isinstance(spec.get("tool"), dict) and item is not None and item.tool is not None:
        _apply(item.tool, spec["tool"], _TOOL_FIELDS)
        if "fluids" in spec["tool"]:
            _restore_fluids(item.tool, spec["tool"].get("fluids"))
    if isinstance(spec.get("oil"), dict) and item is not None:
        host = item.vehicle if spec.get("oil_on") == "vehicle" else item.tool
        _restore_oil(host, spec["oil"])
    if isinstance(spec.get("note"), dict):
        note = _load("notes", row.target_id, hid)
        if note is None:
            return False, "Can't find that note."
        _apply(note, spec["note"], _NOTE_FIELDS)
    if isinstance(spec.get("reminder"), dict):
        reminder = _load("reminders", row.target_id, hid)
        if reminder is None:
            return False, "Can't find that reminder."
        _apply(reminder, spec["reminder"], _REMINDER_FIELDS)
    if isinstance(spec.get("case"), dict):
        case = _load("legal_cases", row.target_id, hid)
        if case is None:
            return False, "Can't find that case."
        _apply(case, spec["case"], _CASE_FIELDS)
    if isinstance(spec.get("record"), dict):
        rec = _load("legal_records", row.target_id, hid)
        if rec is None:
            return False, "Can't find that record."
        _apply(rec, spec["record"], _RECORD_FIELDS)
    if isinstance(spec.get("basket"), dict):
        line = _load("grocery_list", row.target_id, hid)
        if line is None:
            return False, "Can't find that basket line."
        _apply(line, spec["basket"], _BASKET_FIELDS)
    if isinstance(spec.get("log"), dict):
        log = _load("item_logs", row.target_id, hid)
        if log is None:
            return False, "Can't find that log."
        _apply(log, spec["log"], _LOG_FIELDS)
        if isinstance(spec["log"].get("extra_data"), dict):
            log.extra_data = spec["log"]["extra_data"]
    if isinstance(spec.get("part"), dict):
        part = _load("vehicle_parts", row.target_id, hid)
        if part is None:
            return False, "Can't find that part."
        _apply(part, spec["part"], _PART_FIELDS)
    if isinstance(spec.get("living"), dict):
        _restore_living(item, spec["living"])
    label = "That"
    if item is not None and getattr(item, "name", None):
        label = item.name
    return True, f"{label} is put back."


def _restore_living(item, living: dict) -> None:
    if item is None or not isinstance(living, dict):
        return
    if isinstance(living.get("vehicle"), dict) and item.vehicle is not None:
        _restore_oil(item.vehicle, living["vehicle"])
    if isinstance(living.get("tool"), dict) and item.tool is not None:
        _restore_oil(item.tool, living["tool"])


def _trash_one(table: str, row_id: int, hid: int, actor_id) -> tuple[bool, str]:
    from app.utils import maya_store

    if table not in maya_store.TRASHABLE:
        return False, "That one can't be undone."
    obj = _load(table, row_id, hid)
    if obj is None:
        return False, "Can't find that anymore."
    model = _model(table)
    label = getattr(obj, "name", None) or getattr(obj, "title", None) or table
    rows = [(model, obj)]
    rels = []
    for child in list(getattr(obj, "files", None) or []):
        child_table = getattr(type(child), "__tablename__", "")
        if child_table not in maya_store.TRASHABLE or not _same_house(child, hid):
            continue
        rows.append((type(child), child))
        rel = getattr(child, "stored_path", None)
        if rel:
            rels.append(rel)
    maya_store.trash(
        hid=int(hid),
        label=f"Put back: {label}"[:240],
        rows=rows,
        files=rels,
        actor_id=actor_id,
        via="undo",
    )
    return True, f"{label} is in the recycle bin."


def _trash(row, spec: dict, actor_id) -> tuple[bool, str]:
    table = (row.target_table or "").strip()
    ids = spec.get("ids") if isinstance(spec.get("ids"), list) else None
    if not ids:
        ids = [row.target_id]
    item = _load("items", row.item_id, row.household_id) if row.item_id else None
    if isinstance(spec.get("living"), dict):
        _restore_living(item, spec["living"])
    last = "Put away."
    seen = False
    for raw in ids:
        try:
            row_id = int(raw)
        except (TypeError, ValueError):
            continue
        ok, msg = _trash_one(table, row_id, row.household_id, actor_id)
        if not ok:
            return False, msg
        last = msg
        seen = True
    maint = spec.get("maintenance_id")
    if maint:
        ok, msg = _trash_one("maintenance_records", int(maint), row.household_id, actor_id)
        if not ok and msg != "Can't find that anymore.":
            return False, msg
    if not seen:
        return False, "Can't find that anymore."
    return True, last


def _untrash(row, actor_id) -> tuple[bool, str]:
    from app.builddb.table_maya_bot import HouseholdTrash
    from app.utils import maya_store

    entry = HouseholdTrash.query.filter_by(id=row.target_id, household_id=row.household_id).first()
    if entry is None:
        return False, "Can't find that in the recycle bin."
    ok, msg = maya_store.restore(entry, actor_id=actor_id)
    return ok, msg


def _file_version(row, spec, actor_id) -> tuple[bool, str]:
    """Put an archived file version back. Same household only."""
    from app.builddb.table_maya_bot import HouseholdFileVersion
    from app.utils import maya_store

    try:
        vid = int(spec.get("version_id"))
    except (TypeError, ValueError):
        return False, "Can't find that version."
    ver = HouseholdFileVersion.query.filter_by(id=vid, household_id=row.household_id).first()
    if ver is None or ver.restored_at is not None:
        return False, "That version is not available."
    model, _attr = maya_store.kind_model(ver.kind)
    if model is None:
        return False, "Can't find that file anymore."
    target = model.query.filter_by(id=ver.row_id, household_id=row.household_id).first()
    if target is None:
        return False, "Can't find that file anymore."
    ok, msg, _archived = maya_store.restore_version(ver, target, actor_id=actor_id)
    return ok, msg


def undo_recorded(row, *, actor_id=None) -> tuple[bool, str]:
    """Restore one activity row from the undo tag stored on it."""
    spec = row.old_json if isinstance(row.old_json, dict) else {}
    kind = (spec.get("undo") or "").strip()
    action = row.action or ""
    if action.startswith("maya.perms") or action.startswith("bot.vault"):
        return False, "That one can't be undone."
    if kind == "hide_item":
        return _hide_item(row)
    if kind == "retire_part":
        return _retire_part(row)
    if kind == "status":
        return _status(row, spec)
    if kind == "fields":
        return _restore_fields(row, spec)
    if kind == "trash":
        return _trash(row, spec, actor_id)
    if kind == "untrash":
        return _untrash(row, actor_id)
    if kind == "file_version":
        return _file_version(row, spec, actor_id)
    return False, "Don't know how to undo that."
