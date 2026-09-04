from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user

from app.builddb.builddb import db
from app.builddb.table_items import Item, ITEM_TYPES
from app.builddb.table_grocery_items import GroceryItem
from app.builddb.table_grocery_list import GroceryListEntry
from app.builddb.table_maintenance_records import MaintenanceRecord
from app.builddb.table_reminders import Reminder
from app.utils.household import household_id, scoped
from app.utils.permissions import can
from app.utils.scan import process_scan, clamp_qty, _dec
from app.utils.barcode_lookup import lookup_upc, lookup_product
from app.utils.vehicle_lookup import lookup_vehicle
from app.utils.qr_labels import item_payload
from datetime import datetime, timedelta

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.route("/scan", methods=["POST"])
@login_required
def api_scan():
    if not can("scan"):
        return jsonify({"error": "scan not allowed"}), 403
    data = request.get_json(silent=True) or {}
    barcode = (data.get("barcode") or "").strip()
    action = (data.get("action") or "check").strip().lower()
    amount = data.get("amount") or 1
    if not barcode:
        return jsonify({"error": "barcode required"}), 400
    return jsonify(process_scan(household_id(), current_user.id, barcode, action, amount))


@api_bp.route("/barcode-lookup")
@login_required
def api_lookup():
    code = (request.args.get("barcode") or "").strip()
    return jsonify(lookup_product(code))


@api_bp.route("/lookup/product")
@login_required
def api_lookup_product():
    code = (request.args.get("barcode") or "").strip()
    return jsonify(lookup_product(code))


@api_bp.route("/lookup/vehicle")
@login_required
def api_lookup_vehicle():
    plate = (request.args.get("plate") or "").strip()
    vin = (request.args.get("vin") or "").strip()
    return jsonify(lookup_vehicle(plate=plate, vin=vin))


@api_bp.route("/items", methods=["POST"])
@login_required
def api_create_item():
    if not (can("edit_meta") or can("edit_grocery")):
        return jsonify({"error": "not allowed"}), 403
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    item_type = str(data.get("item_type") or "grocery").strip().lower()
    if not can("edit_meta"):
        item_type = "grocery"
    if item_type not in ITEM_TYPES:
        item_type = "grocery"
    hid = household_id()
    barcode = (data.get("barcode") or "").strip() or None
    if barcode and Item.query.filter_by(household_id=hid, barcode=barcode).first():
        return jsonify({"error": "barcode already exists"}), 409
    item = Item(
        household_id=hid,
        name=name,
        item_type=item_type,
        category=(data.get("category") or "").strip() or None,
        barcode=barcode,
        created_by=current_user.id,
    )
    db.session.add(item)
    db.session.flush()
    if not item.barcode:
        item.barcode = item_payload(hid, item.id)
    if item_type == "grocery":
        g = GroceryItem(
            item_id=item.id,
            household_id=hid,
            quantity=clamp_qty(data.get("quantity") or 1, "1"),
            restock_threshold=clamp_qty(data.get("restock_threshold") or 1, "1"),
        )
        g.is_in_stock = g.quantity > 0
        g.needs_restock = g.quantity <= g.restock_threshold
        db.session.add(g)
    db.session.commit()
    return jsonify({"ok": True, "item_id": item.id, "barcode": item.barcode})


@api_bp.route("/maintenance", methods=["POST"])
@login_required
def api_maintenance():
    if not can("maintain"):
        return jsonify({"error": "not allowed"}), 403
    data = request.get_json(silent=True) or {}
    item_id = data.get("item_id")
    item = scoped(Item).filter_by(id=item_id).first()
    if not item:
        return jsonify({"error": "item not found"}), 404
    date_s = (data.get("date") or "").strip()
    try:
        date = datetime.strptime(date_s, "%Y-%m-%d").date() if date_s else datetime.utcnow().date()
    except ValueError:
        date = datetime.utcnow().date()
    rec = MaintenanceRecord(
        household_id=household_id(),
        parent_type=item.item_type,
        parent_id=item.id,
        type=(data.get("type") or "maintenance"),
        date=date,
        mileage_or_hours=_dec(data.get("mileage_or_hours"), "0") if data.get("mileage_or_hours") else None,
        notes=(data.get("notes") or "").strip() or None,
        photos=data.get("photos") or [],
        created_by=current_user.id,
    )
    db.session.add(rec)
    if item.tool:
        item.tool.last_maintenance_at = datetime.utcnow()
    if item.vehicle and rec.type in ("oil_change", "oil change", "oil"):
        item.vehicle.last_oil_change_date = date
        if rec.mileage_or_hours is not None:
            item.vehicle.last_oil_change_mileage = int(rec.mileage_or_hours)
            item.vehicle.current_mileage = int(rec.mileage_or_hours)
        db.session.add(
            Reminder(
                household_id=household_id(),
                linked_item_id=item.id,
                type="oil_change",
                title=f"Next oil change — {item.name}",
                due_at=datetime.utcnow() + timedelta(days=180),
                recurrence="180d",
                status="open",
                created_by=current_user.id,
            )
        )
    db.session.commit()
    return jsonify({"ok": True, "id": rec.id})


@api_bp.route("/grocery-list")
@login_required
def api_grocery_list():
    rows = (
        scoped(GroceryListEntry)
        .filter_by(status="open")
        .order_by(GroceryListEntry.created_at.desc())
        .all()
    )
    return jsonify(
        {
            "items": [
                {
                    "id": r.id,
                    "name": r.name,
                    "item_id": r.item_id,
                    "quantity_needed": float(r.quantity_needed) if r.quantity_needed is not None else None,
                    "reason": r.added_reason,
                }
                for r in rows
            ]
        }
    )
