from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from app.builddb.builddb import db
from app.builddb.table_items import Item
from app.builddb.table_vehicles import Vehicle
from app.utils.household import household_id
from app.utils.permissions import can
from app.utils.vehicle_lookup import lookup_vehicle, apply_vehicle_lookup
from app.utils.qr_labels import item_payload

vehicles_bp = Blueprint("vehicles", __name__, url_prefix="/vehicles")


@vehicles_bp.route("/")
@login_required
def index():
    hid = household_id()
    items = (
        Item.query.filter_by(household_id=hid, item_type="vehicle")
        .order_by(Item.name.asc())
        .all()
    )
    return render_template("vehicles.html", items=items, can_add=can("edit_meta") or can("maintain"))


@vehicles_bp.route("/lookup", methods=["POST"])
@login_required
def add_from_lookup():
    if not (can("edit_meta") or can("maintain")):
        abort(403)
    hid = household_id()
    plate = (request.form.get("plate") or "").strip().upper()
    vin = (request.form.get("vin") or "").strip().upper()
    typed_name = (request.form.get("name") or "").strip()
    make = (request.form.get("make") or "").strip()
    model = (request.form.get("model") or "").strip()
    year = (request.form.get("year") or "").strip()
    if not (plate or vin or typed_name or make or model):
        flash("Scan a QR, or type a plate, VIN, or name.", "danger")
        return redirect(url_for("vehicles.index"))
    decoded = lookup_vehicle(plate=plate, vin=vin) if (plate or vin) else {"ok": True, "facts": {}, "recalls": []}
    name = (
        typed_name
        or decoded.get("name")
        or " ".join(x for x in (year, make, model) if x)
        or (f"Plate {plate}" if plate else None)
        or (f"VIN {vin[:8]}" if vin else "Vehicle")
    )
    if vin:
        clash = Vehicle.query.filter_by(household_id=hid).filter(Vehicle.vin == vin).first()
        if clash:
            flash("That VIN is already in this household.", "warning")
            return redirect(url_for("items.detail", item_id=clash.item_id))
    item = Item(
        household_id=hid,
        name=name[:200],
        item_type="vehicle",
        created_by=current_user.id,
    )
    db.session.add(item)
    db.session.flush()
    item.barcode = item_payload(hid, item.id)
    v = Vehicle(item_id=item.id, household_id=hid)
    db.session.add(v)
    apply_vehicle_lookup(v, item, decoded)
    if make:
        v.make = make[:80]
    if model:
        v.model = model[:80]
    if year.isdigit():
        v.year = int(year)
    db.session.commit()
    if decoded.get("need_vin"):
        flash(decoded.get("message") or "Plate saved. Add the VIN for factory specs.", "warning")
    elif decoded.get("ok"):
        flash(f"{item.name} filled from NHTSA.", "success")
    else:
        flash(decoded.get("error") or "Saved, but lookup did not fill specs.", "warning")
    return redirect(url_for("items.detail", item_id=item.id))
