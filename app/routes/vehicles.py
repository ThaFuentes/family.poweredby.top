from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from app.builddb.builddb import db
from app.builddb.table_items import Item
from app.builddb.table_vehicles import Vehicle
from app.builddb.table_vehicle_parts import VehiclePart
from app.utils.household import household_id, scoped
from app.utils.permissions import can
from app.utils.vehicle_lookup import lookup_vehicle, apply_vehicle_lookup
from app.utils.qr_labels import item_payload
from app.utils.vehicle_systems import install_part, valid_slot, valid_system
from app.routes.items import attach_part_uploads, save_item_photo, _item_or_404

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
    photo = request.files.get("photo")
    if photo and photo.filename:
        save_item_photo(item, photo, request.form.get("caption"), current_user.id)
    db.session.commit()
    if decoded.get("need_vin"):
        flash(decoded.get("message") or "Plate saved. Add the VIN for factory specs.", "warning")
    elif decoded.get("ok"):
        flash(f"{item.name} filled from NHTSA.", "success")
    else:
        flash(decoded.get("error") or "Saved, but lookup did not fill specs.", "warning")
    return redirect(url_for("items.detail", item_id=item.id, tab="systems"))


def _vehicle_item(item_id):
    item = _item_or_404(item_id)
    if item.item_type != "vehicle":
        abort(404)
    return item


@vehicles_bp.route("/<int:item_id>/parts", methods=["POST"])
@login_required
def add_part(item_id):
    if not (can("maintain") or can("edit_meta")):
        abort(403)
    item = _vehicle_item(item_id)
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Name the part — DieHard Group 65, 130A alternator, 5W-30.", "danger")
        return redirect(url_for("items.detail", item_id=item.id, tab="systems"))
    hid = household_id()
    system = valid_system(request.form.get("system"))
    slot = valid_slot(system, request.form.get("slot"))
    status = (request.form.get("status") or "installed").strip().lower()
    row = install_part(
        hid=hid,
        vehicle_item_id=item.id,
        user_id=current_user.id,
        system=system,
        slot=slot,
        name=name,
        brand=request.form.get("brand"),
        spec=request.form.get("spec"),
        part_number=request.form.get("part_number"),
        status=status,
        installed_on=request.form.get("installed_on"),
        installed_mileage=request.form.get("installed_mileage") or (item.vehicle.current_mileage if item.vehicle else None),
        notes=request.form.get("notes"),
        source=request.form.get("source"),
        cost=request.form.get("cost"),
        warranty_until=request.form.get("warranty_until"),
        replace_current=status == "installed",
    )
    nfiles = attach_part_uploads(item, row, current_user.id)
    db.session.commit()
    extra = f" {nfiles} file(s)." if nfiles else ""
    flash(f"{name} saved on {item.name}.{extra}", "success")
    return redirect(url_for("items.detail", item_id=item.id, tab="systems") + (f"#sys-{row.system}" if row else ""))


@vehicles_bp.route("/<int:item_id>/parts/<int:part_id>/retire", methods=["POST"])
@login_required
def retire_part(item_id, part_id):
    if not (can("maintain") or can("edit_meta")):
        abort(403)
    item = _vehicle_item(item_id)
    row = (
        VehiclePart.query.filter_by(
            id=part_id, household_id=household_id(), vehicle_item_id=item.id
        ).first_or_404()
    )
    row.is_current = False
    row.status = "retired"
    db.session.commit()
    flash(f"{row.name} moved to history.", "info")
    return redirect(url_for("items.detail", item_id=item.id, tab="systems"))
