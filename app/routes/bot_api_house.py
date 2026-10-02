"""fos_bot_ views: vehicles, notes, attachments, inventory, records.

Every query is filtered to the session's household. Writes are whitelisted
column assignments — a body key that is not on the field list is ignored
rather than mass-assigned. Nothing here deletes; v1 has no DELETE.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from flask import request

from app.builddb.builddb import db
from app.routes.bot_api import (
    BOT,
    as_date,
    as_dec,
    as_int,
    as_num,
    as_str,
    bot_api_bp,
    limit_arg,
    note_activity,
    offset_arg,
    ok,
    page,
)
from app.utils.bot_api_access import gate, inventory_write_allowed, note_edit_allowed
from app.utils.bot_api_auth import (
    api_error,
    api_household_id,
    api_scope,
    api_user,
    body,
    bot_api,
    iso,
    iso_date,
)

VEHICLE_STR = {
    "make": 80,
    "model": 80,
    "vin": 32,
    "plate": 20,
    "color": 40,
    "trim": 80,
    "body_class": 80,
    "drive_type": 80,
    "fuel_type": 80,
    "engine": 160,
    "transmission": 80,
    "oil_type": 80,
    "oil_needs": 200,
    "oil_capacity": 40,
    "filter_type": 80,
    "tire_size": 40,
    "battery_type": 80,
}
VEHICLE_INT = (
    "year",
    "current_mileage",
    "last_oil_change_mileage",
    "oil_interval_miles",
    "oil_interval_months",
)
VEHICLE_DATE = ("last_oil_change_date", "next_oil_due_date")


def _apply_vehicle(veh, data: dict) -> list[str]:
    touched: list[str] = []
    for key, maxlen in VEHICLE_STR.items():
        if key in data:
            value = as_str(data, key, maxlen)
            if value is not None:
                setattr(veh, key, value)
                touched.append(key)
    for key in VEHICLE_INT:
        if key in data:
            value = as_int(data, key)
            if value is not None:
                setattr(veh, key, value)
                touched.append(key)
    for key in VEHICLE_DATE:
        if key in data:
            value = as_date(data, key)
            if value is not None:
                setattr(veh, key, value)
                touched.append(key)
    return touched


def _vehicle_json(item):
    v = item.vehicle
    return {
        "id": item.id,
        "name": item.name,
        "item_type": item.item_type,
        "category": item.category,
        "notes": item.notes,
        "tags": item.tags,
        "vehicle": None
        if v is None
        else {
            **{k: getattr(v, k) for k in VEHICLE_STR},
            **{k: getattr(v, k) for k in VEHICLE_INT},
            "last_oil_change_date": iso_date(v.last_oil_change_date),
            "next_oil_due_date": iso_date(v.next_oil_due_date),
            "extra_data": v.extra_data,
        },
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }


def _vehicle_or_404(ident):
    from app.builddb.table_items import Item

    return api_scope(Item).filter_by(id=ident, item_type="vehicle").first()


@bot_api_bp.route("/vehicles")
@bot_api(BOT)
def vehicles_list():
    blocked = gate("view", "scan")
    if blocked:
        return blocked
    from app.builddb.table_items import Item

    q = api_scope(Item).filter_by(item_type="vehicle").order_by(Item.name.asc())
    total = q.count()
    rows = q.offset(offset_arg()).limit(limit_arg()).all()
    return ok({"vehicles": [_vehicle_json(r) for r in rows], **page(rows, total)})


@bot_api_bp.route("/vehicles/<int:item_id>")
@bot_api(BOT)
def vehicles_get(item_id):
    blocked = gate("view", "scan")
    if blocked:
        return blocked
    item = _vehicle_or_404(item_id)
    if item is None:
        return api_error("No such vehicle in this household.", 404, "not_found")
    return ok({"vehicle": _vehicle_json(item)})


@bot_api_bp.route("/vehicles", methods=["POST"])
@bot_api(BOT, write=True)
def vehicles_create():
    blocked = gate("maintain", "edit_meta")
    if blocked:
        return blocked
    from app.builddb.table_items import Item
    from app.builddb.table_vehicles import Vehicle

    data = body()
    name = as_str(data, "name", 200)
    if not name:
        return api_error("name is required.", 400, "bad_request")
    item = Item(
        household_id=api_household_id(),
        item_type="vehicle",
        name=name,
        category=as_str(data, "category", 100),
        tags=data.get("tags") if isinstance(data.get("tags"), list) else None,
        notes=as_str(data, "notes", 5000),
        created_by=getattr(api_user(), "id", None),
    )
    db.session.add(item)
    db.session.flush()
    veh = Vehicle(household_id=api_household_id(), item_id=item.id)
    _apply_vehicle(veh, data)
    db.session.add(veh)
    db.session.commit()
    note_activity(
        "bot.vehicle.add",
        f"A bot added the vehicle {item.name}",
        target_table="items",
        target_id=item.id,
    )
    return ok({"vehicle": _vehicle_json(item)}, 201)


@bot_api_bp.route("/vehicles/<int:item_id>", methods=["PATCH"])
@bot_api(BOT, write=True)
def vehicles_update(item_id):
    blocked = gate("maintain", "edit_meta")
    if blocked:
        return blocked
    from app.builddb.table_vehicles import Vehicle

    item = _vehicle_or_404(item_id)
    if item is None:
        return api_error("No such vehicle in this household.", 404, "not_found")
    data = body()
    item.name = as_str(data, "name", 200) or item.name
    item.category = as_str(data, "category", 100) or item.category
    if "notes" in data:
        item.notes = as_str(data, "notes", 5000) or None
    veh = item.vehicle or Vehicle(household_id=api_household_id(), item_id=item.id)
    _apply_vehicle(veh, data)
    db.session.add(veh)
    db.session.add(item)
    db.session.commit()
    note_activity(
        "bot.vehicle.update",
        f"A bot updated the vehicle {item.name}",
        target_table="items",
        target_id=item.id,
    )
    return ok({"vehicle": _vehicle_json(item)})


# ---------------------------------------------------------------- notes


def _note_json(note, with_files: bool = True):
    from app.utils.crypto import decrypt_text

    out = {
        "id": note.id,
        "title": decrypt_text(note.title) or "",
        "body": decrypt_text(note.body),
        "visibility": note.visibility,
        "item_id": note.item_id,
        "created_by": note.user_id,
        "created_at": iso(note.created_at),
        "updated_at": iso(note.updated_at),
    }
    if with_files:
        out["files"] = [_file_json(f) for f in (note.files or [])]
    return out


def _file_json(row):
    from app.utils.crypto import decrypt_text

    return {
        "id": row.id,
        "note_id": row.note_id,
        "original_name": row.original_name,
        "mime": row.mime,
        "caption": decrypt_text(row.caption),
        "download": f"/api/v1/files/{row.id}",
        "created_at": iso(row.created_at),
    }


def visible_notes():
    """Household notes plus this bot's own — same rule the Notes page uses."""
    from sqlalchemy import or_

    from app.builddb.table_notes import Note

    return api_scope(Note).filter(
        or_(Note.visibility == "household", Note.user_id == getattr(api_user(), "id", 0))
    )


def note_or_404(note_id):
    return visible_notes().filter_by(id=note_id).first()


@bot_api_bp.route("/notes")
@bot_api(BOT)
def notes_list():
    blocked = gate("view", "scan")
    if blocked:
        return blocked
    from app.builddb.table_notes import Note

    q = visible_notes().order_by(Note.updated_at.desc())
    scope = (request.args.get("scope") or "").strip().lower()
    if scope == "household":
        q = q.filter_by(visibility="household")
    total = q.count()
    rows = q.offset(offset_arg()).limit(limit_arg()).all()
    return ok({"notes": [_note_json(r) for r in rows], **page(rows, total)})


@bot_api_bp.route("/notes/<int:note_id>")
@bot_api(BOT)
def notes_get(note_id):
    blocked = gate("view", "scan")
    if blocked:
        return blocked
    note = note_or_404(note_id)
    if note is None:
        return api_error("No such note in this household.", 404, "not_found")
    return ok({"note": _note_json(note)})


@bot_api_bp.route("/notes", methods=["POST"])
@bot_api(BOT, write=True)
def notes_create():
    blocked = gate("view", "scan")
    if blocked:
        return blocked
    from app.builddb.table_items import Item
    from app.builddb.table_notes import VISIBILITY, Note

    data = body()
    title = as_str(data, "title", 500)
    if not title:
        return api_error("title is required.", 400, "bad_request")
    vis = (as_str(data, "visibility", 20) or "household").lower()
    if vis not in VISIBILITY:
        vis = "household"
    item_id = as_int(data, "item_id")
    if item_id is not None and api_scope(Item).filter_by(id=item_id).first() is None:
        return api_error("No such item in this household.", 404, "not_found")
    note = Note(
        household_id=api_household_id(),
        user_id=getattr(api_user(), "id", 0),
        item_id=item_id,
        visibility=vis,
        title=title,
        body=as_str(data, "body", 20000),
    )
    db.session.add(note)
    db.session.commit()
    note_activity(
        "bot.note.add",
        f"A bot added the note {title}",
        target_table="notes",
        target_id=note.id,
        item_id=item_id,
    )
    return ok({"note": _note_json(note)}, 201)


@bot_api_bp.route("/notes/<int:note_id>", methods=["PATCH"])
@bot_api(BOT, write=True)
def notes_update(note_id):
    from app.builddb.table_items import Item
    from app.builddb.table_notes import VISIBILITY

    blocked = gate("view", "scan")
    if blocked:
        return blocked
    note = note_or_404(note_id)
    if note is None:
        return api_error("No such note in this household.", 404, "not_found")
    if not note_edit_allowed(note):
        return api_error("This account cannot change that note.", 403, "forbidden")
    data = body()
    if "title" in data:
        note.title = as_str(data, "title", 500) or note.title
    if "body" in data:
        note.body = as_str(data, "body", 20000) or None
    if "visibility" in data:
        vis = (as_str(data, "visibility", 20) or "").lower()
        if vis in VISIBILITY:
            note.visibility = vis
    if "item_id" in data:
        item_id = as_int(data, "item_id")
        if item_id is None:
            note.item_id = None
        elif api_scope(Item).filter_by(id=item_id).first() is not None:
            note.item_id = item_id
        else:
            return api_error("No such item in this household.", 404, "not_found")
    note.updated_at = datetime.utcnow()
    db.session.add(note)
    db.session.commit()
    note_activity(
        "bot.note.update",
        f"A bot updated the note {note.title}",
        target_table="notes",
        target_id=note.id,
    )
    return ok({"note": _note_json(note)})


# --------------------------------------------------------- attachments


@bot_api_bp.route("/notes/<int:note_id>/files")
@bot_api(BOT)
def files_list(note_id):
    blocked = gate("view", "scan")
    if blocked:
        return blocked
    note = note_or_404(note_id)
    if note is None:
        return api_error("No such note in this household.", 404, "not_found")
    return ok({"files": [_file_json(f) for f in (note.files or [])]})


@bot_api_bp.route("/notes/<int:note_id>/files", methods=["POST"])
@bot_api(BOT, write=True)
def files_add(note_id):
    from app.routes.notes import save_note_file

    blocked = gate("view", "scan")
    if blocked:
        return blocked
    note = note_or_404(note_id)
    if note is None:
        return api_error("No such note in this household.", 404, "not_found")
    if not note_edit_allowed(note):
        return api_error("This account cannot change that note.", 403, "forbidden")
    upload = request.files.get("file") or request.files.get("photo")
    if upload is None or not getattr(upload, "filename", ""):
        return api_error(
            "Attach a photo or PDF as the multipart field 'file'.", 400, "no_file"
        )
    row = save_note_file(
        note, upload, getattr(api_user(), "id", None), as_str(body(), "caption", 300)
    )
    if row is None:
        return api_error(
            "That file type is not allowed (jpg, jpeg, png, webp, gif, pdf) or it is over 20 MB.",
            400,
            "file_rejected",
        )
    note.updated_at = datetime.utcnow()
    db.session.commit()
    note_activity(
        "bot.note.file",
        f"A bot attached a file to the note {note.title}",
        target_table="notes",
        target_id=note.id,
    )
    return ok({"file": _file_json(row)}, 201)


@bot_api_bp.route("/files/<int:file_id>")
@bot_api(BOT)
def files_get(file_id):
    blocked = gate("view", "scan")
    if blocked:
        return blocked
    from sqlalchemy.orm import selectinload

    from app.builddb.table_note_files import NoteFile
    from app.routes.notes import resolve_note_file
    from app.utils.crypto import read_decrypted_file, send_bytes

    row = (
        api_scope(NoteFile)
        .options(selectinload(NoteFile.note))
        .filter_by(id=file_id)
        .first()
    )
    # Check through the note, not the file: a personal note this bot cannot
    # see must not be downloadable by guessing file ids.
    if row is None or row.note is None or note_or_404(row.note_id) is None:
        return api_error("No such file in this household.", 404, "not_found")
    data = read_decrypted_file(str(resolve_note_file(row)))
    if not data:
        return api_error("That file could not be read.", 404, "not_found")
    return send_bytes(data, row.mime or "application/octet-stream", row.original_name or "file")


# ------------------------------------------------------------ inventory


def _inventory_json(item):
    g = item.grocery
    return {
        "id": item.id,
        "name": item.name,
        "item_type": item.item_type,
        "category": item.category,
        "barcode": item.barcode,
        "notes": item.notes,
        "extra_data": item.extra_data,
        "grocery": None
        if g is None
        else {
            "quantity": as_num(g.quantity),
            "restock_threshold": as_num(g.restock_threshold),
            "is_in_stock": bool(g.is_in_stock),
            "needs_restock": bool(g.needs_restock),
            "location": g.default_location,
            "brand": g.brand,
            "size": g.size,
            "unit": g.unit,
            "auto_basket": bool(g.auto_basket),
            "last_consumed_at": iso(g.last_consumed_at),
            "last_restocked_at": iso(g.last_restocked_at),
            "consume_count": g.consume_count,
        },
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }


def _sync_stock(g) -> None:
    """Same clamp + stock flags the scan path uses, so counts agree."""
    from app.utils.scan import clamp_qty

    g.quantity = clamp_qty(g.quantity)
    g.restock_threshold = clamp_qty(g.restock_threshold, "1")
    g.is_in_stock = g.quantity > 0
    g.needs_restock = g.quantity <= g.restock_threshold


@bot_api_bp.route("/inventory")
@bot_api(BOT)
def inventory_list():
    blocked = gate("view", "scan")
    if blocked:
        return blocked
    from app.builddb.table_items import Item

    q = api_scope(Item).filter(Item.item_type.in_(("grocery", "house", "tool", "custom")))
    search = (request.args.get("q") or "").strip()
    if search:
        q = q.filter(Item.name.ilike(f"%{search}%"))
    q = q.order_by(Item.name.asc())
    total = q.count()
    rows = q.offset(offset_arg()).limit(limit_arg()).all()
    return ok({"items": [_inventory_json(r) for r in rows], **page(rows, total)})


@bot_api_bp.route("/inventory/<int:item_id>")
@bot_api(BOT)
def inventory_get(item_id):
    blocked = gate("view", "scan")
    if blocked:
        return blocked
    from app.builddb.table_items import Item

    item = api_scope(Item).filter_by(id=item_id).first()
    if item is None:
        return api_error("No such item in this household.", 404, "not_found")
    return ok({"item": _inventory_json(item)})


@bot_api_bp.route("/inventory", methods=["POST"])
@bot_api(BOT, write=True)
def inventory_create():
    from app.builddb.table_grocery_items import GroceryItem
    from app.builddb.table_items import Item
    from app.utils.qr_labels import item_payload

    data = body()
    name = as_str(data, "name", 200)
    if not name:
        return api_error("name is required.", 400, "bad_request")
    item_type = (as_str(data, "item_type", 20) or "grocery").lower()
    if not inventory_write_allowed(item_type, data, creating=True):
        return api_error("This account cannot add that.", 403, "forbidden")
    if item_type not in ("grocery", "tool", "house", "custom"):
        item_type = "grocery"
    hid = api_household_id()
    barcode = as_str(data, "barcode", 80)
    if barcode and Item.query.filter_by(household_id=hid, barcode=barcode).first():
        return api_error("That barcode is already in this household.", 409, "barcode_taken")
    item = Item(
        household_id=hid,
        item_type=item_type,
        name=name,
        category=as_str(data, "category", 100),
        barcode=barcode,
        notes=as_str(data, "notes", 5000),
        created_by=getattr(api_user(), "id", None),
    )
    db.session.add(item)
    db.session.flush()
    if not item.barcode:
        item.barcode = item_payload(hid, item.id)
    g = GroceryItem(
        item_id=item.id,
        household_id=hid,
        quantity=as_dec(data, "quantity", Decimal("0")) or Decimal("0"),
        restock_threshold=as_dec(data, "restock_threshold", Decimal("1")) or Decimal("1"),
        default_location=as_str(data, "location", 120),
        brand=as_str(data, "brand", 120),
        size=as_str(data, "size", 80),
        unit=as_str(data, "unit", 40) or "each",
    )
    _sync_stock(g)
    db.session.add(g)
    db.session.commit()
    note_activity(
        "bot.inventory.add",
        f"A bot added {item.name} to the house",
        target_table="items",
        target_id=item.id,
    )
    return ok({"item": _inventory_json(item)}, 201)


@bot_api_bp.route("/inventory/<int:item_id>", methods=["PATCH"])
@bot_api(BOT, write=True)
def inventory_update(item_id):
    from app.builddb.table_grocery_items import GroceryItem
    from app.builddb.table_items import Item

    item = api_scope(Item).filter_by(id=item_id).first()
    if item is None:
        return api_error("No such item in this household.", 404, "not_found")
    data = body()
    if not inventory_write_allowed(item.item_type, data, creating=False):
        return api_error("This account cannot change that.", 403, "forbidden")
    item.name = as_str(data, "name", 200) or item.name
    item.category = as_str(data, "category", 100) or item.category
    if "notes" in data:
        item.notes = as_str(data, "notes", 5000) or None
    g = item.grocery
    if g is None:
        g = GroceryItem(item_id=item.id, household_id=api_household_id())
        db.session.add(g)
    for key, field in (
        ("quantity", "quantity"),
        ("restock_threshold", "restock_threshold"),
    ):
        if key in data:
            value = as_dec(data, key)
            if value is not None:
                setattr(g, field, value)
    g.default_location = as_str(data, "location", 120) or g.default_location
    g.brand = as_str(data, "brand", 120) or g.brand
    g.size = as_str(data, "size", 80) or g.size
    g.unit = as_str(data, "unit", 40) or g.unit
    _sync_stock(g)
    db.session.add(g)
    db.session.add(item)
    db.session.commit()
    note_activity(
        "bot.inventory.set",
        f"A bot set {item.name} in the house",
        target_table="items",
        target_id=item.id,
    )
    return ok({"item": _inventory_json(item)})


# -------------------------------------------------------------- records


def _record_json(rec, with_files: bool = True):
    from app.utils.crypto import decrypt_text

    out = {
        "id": rec.id,
        "kind": rec.kind,
        "status": rec.status,
        "title": decrypt_text(rec.title) or "",
        "agency": decrypt_text(rec.agency),
        "case_number": decrypt_text(rec.case_number),
        "location": decrypt_text(rec.location),
        "issued_on": iso_date(rec.issued_on),
        "due_on": iso_date(rec.due_on),
        "amount": as_num(rec.amount),
        "body": decrypt_text(rec.body),
        "outcome": decrypt_text(rec.outcome),
        "case_id": rec.case_id,
        "created_by": rec.created_by,
        "created_at": iso(rec.created_at),
        "updated_at": iso(rec.updated_at),
    }
    if with_files:
        out["files"] = [
            {"id": f.id, "original_name": f.original_name, "mime": f.mime}
            for f in (rec.files or [])
        ]
    return out


@bot_api_bp.route("/records")
@bot_api(BOT)
def records_list():
    blocked = gate("legal")
    if blocked:
        return blocked
    from app.builddb.table_legal_records import LegalRecord

    q = api_scope(LegalRecord).order_by(LegalRecord.issued_on.desc())
    status = (request.args.get("status") or "").strip().lower()
    if status:
        q = q.filter_by(status=status)
    total = q.count()
    rows = q.offset(offset_arg()).limit(limit_arg()).all()
    return ok({"records": [_record_json(r) for r in rows], **page(rows, total)})


@bot_api_bp.route("/records/<int:record_id>")
@bot_api(BOT)
def records_get(record_id):
    blocked = gate("legal")
    if blocked:
        return blocked
    from app.builddb.table_legal_records import LegalRecord

    rec = api_scope(LegalRecord).filter_by(id=record_id).first()
    if rec is None:
        return api_error("No such record in this household.", 404, "not_found")
    return ok({"record": _record_json(rec)})


@bot_api_bp.route("/records", methods=["POST"])
@bot_api(BOT, write=True)
def records_create():
    blocked = gate("legal")
    if blocked:
        return blocked
    from app.builddb.table_legal_records import KINDS, STATUSES, LegalRecord

    data = body()
    title = as_str(data, "title", 500)
    if not title:
        return api_error("title is required.", 400, "bad_request")
    kind = (as_str(data, "kind", 20) or "citation").lower()
    kind = kind if kind in KINDS else "other"
    status = (as_str(data, "status", 20) or "open").lower()
    status = status if status in STATUSES else "open"
    rec = LegalRecord(
        household_id=api_household_id(),
        created_by=getattr(api_user(), "id", None),
        kind=kind,
        status=status,
        title=title,
        agency=as_str(data, "agency", 300),
        case_number=as_str(data, "case_number", 120),
        location=as_str(data, "location", 300),
        issued_on=as_date(data, "issued_on"),
        due_on=as_date(data, "due_on"),
        amount=as_dec(data, "amount"),
        body=as_str(data, "body", 20000),
    )
    db.session.add(rec)
    db.session.commit()
    note_activity(
        "bot.record.add",
        f"A bot filed the record {title}",
        target_table="legal_records",
        target_id=rec.id,
    )
    return ok({"record": _record_json(rec)}, 201)


@bot_api_bp.route("/records/<int:record_id>", methods=["PATCH"])
@bot_api(BOT, write=True)
def records_update(record_id):
    blocked = gate("legal")
    if blocked:
        return blocked
    from app.builddb.table_legal_records import KINDS, STATUSES, LegalRecord

    rec = api_scope(LegalRecord).filter_by(id=record_id).first()
    if rec is None:
        return api_error("No such record in this household.", 404, "not_found")
    data = body()
    if "title" in data:
        rec.title = as_str(data, "title", 500) or rec.title
    if "kind" in data:
        kind = (as_str(data, "kind", 20) or "").lower()
        if kind in KINDS:
            rec.kind = kind
    if "status" in data:
        status = (as_str(data, "status", 20) or "").lower()
        if status in STATUSES:
            rec.status = status
    for key, maxlen in (
        ("agency", 300),
        ("case_number", 120),
        ("location", 300),
        ("body", 20000),
        ("outcome", 20000),
    ):
        if key in data:
            setattr(rec, key, as_str(data, key, maxlen) or None)
    for key in ("issued_on", "due_on"):
        if key in data:
            value = as_date(data, key)
            if value is not None:
                setattr(rec, key, value)
    if "amount" in data:
        value = as_dec(data, "amount")
        if value is not None:
            rec.amount = value
    db.session.add(rec)
    db.session.commit()
    note_activity(
        "bot.record.update",
        f"A bot updated the record {rec.title}",
        target_table="legal_records",
        target_id=rec.id,
    )
    return ok({"record": _record_json(rec)})