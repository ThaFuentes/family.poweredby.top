import os
import secrets
from datetime import datetime, timedelta
from decimal import Decimal

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
    send_from_directory,
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from app.builddb.builddb import db
from app.builddb.table_items import Item, ITEM_TYPES
from app.builddb.table_grocery_items import GroceryItem
from app.builddb.table_tools import Tool
from app.builddb.table_vehicles import Vehicle
from app.builddb.table_maintenance_records import MaintenanceRecord
from app.builddb.table_reminders import Reminder
from app.builddb.table_photo_notes import PhotoNote
from app.builddb.table_scan_events import ScanEvent
from app.utils.household import household_id, scoped
from app.utils.permissions import can, require_perm
from app.utils.qr_labels import ensure_item_barcode, qr_png_response, item_payload
from app.utils.scan import apply_grocery_stock, _dec

items_bp = Blueprint("items", __name__, url_prefix="/items")

ALLOWED_PHOTO = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _item_or_404(item_id):
    return scoped(Item).filter_by(id=item_id).first_or_404()


def _uploads_root():
    root = os.path.join(os.path.dirname(current_app.root_path), "uploads")
    os.makedirs(root, exist_ok=True)
    return root


@items_bp.route("/new")
@login_required
def new_item():
    if not (can("edit_meta") or can("edit_grocery")):
        flash("Ask a household admin to add new items.", "warning")
        abort(403)
    barcode = (request.args.get("barcode") or "").strip()
    suggested = (request.args.get("type") or "grocery").strip().lower()
    if suggested not in ITEM_TYPES:
        suggested = "grocery"
    if not can("edit_meta"):
        suggested = "grocery"
    lookup = {}
    if barcode and barcode.isdigit():
        try:
            from app.utils.barcode_lookup import lookup_upc

            lookup = lookup_upc(barcode)
        except Exception:
            lookup = {}
    return render_template(
        "item_create.html",
        barcode=barcode,
        suggested=suggested,
        lookup=lookup,
        types=ITEM_TYPES,
    )


def _attach_type_row(item, form):
    hid = item.household_id
    if item.item_type == "grocery":
        g = GroceryItem.query.filter_by(item_id=item.id, household_id=hid).first()
        if g is None:
            g = GroceryItem(item_id=item.id, household_id=hid)
            db.session.add(g)
        g.quantity = _dec(form.get("quantity") or 1, "1")
        g.restock_threshold = _dec(form.get("restock_threshold") or 1, "1")
        g.brand = (form.get("brand") or "").strip() or None
        g.size = (form.get("size") or "").strip() or None
        g.unit = (form.get("unit") or "each").strip() or "each"
        g.default_location = (form.get("default_location") or "").strip() or None
        g.is_in_stock = g.quantity > 0
        g.needs_restock = g.quantity <= g.restock_threshold
    elif item.item_type == "tool":
        t = Tool.query.filter_by(item_id=item.id, household_id=hid).first()
        if t is None:
            t = Tool(item_id=item.id, household_id=hid)
            db.session.add(t)
        t.type = (form.get("tool_type") or "").strip() or None
        t.power_source = (form.get("power_source") or "").strip() or None
        t.oil_type = (form.get("oil_type") or "").strip() or None
        t.fuel_type = (form.get("fuel_type") or "").strip() or None
        t.usage_notes = (form.get("usage_notes") or "").strip() or None
        hours = form.get("maintenance_interval_hours") or ""
        t.maintenance_interval_hours = int(hours) if str(hours).isdigit() else None
    elif item.item_type == "vehicle":
        v = Vehicle.query.filter_by(item_id=item.id, household_id=hid).first()
        if v is None:
            v = Vehicle(item_id=item.id, household_id=hid)
            db.session.add(v)
        v.make = (form.get("make") or "").strip() or None
        v.model = (form.get("model") or "").strip() or None
        year = form.get("year") or ""
        v.year = int(year) if str(year).isdigit() else None
        v.vin = (form.get("vin") or "").strip() or None
        v.oil_type = (form.get("oil_type") or "").strip() or None
        v.filter_type = (form.get("filter_type") or "").strip() or None
        v.tire_size = (form.get("tire_size") or "").strip() or None
        v.battery_type = (form.get("battery_type") or "").strip() or None
        miles = form.get("current_mileage") or ""
        v.current_mileage = int(miles) if str(miles).isdigit() else None
        v.manual_url = (form.get("manual_url") or "").strip() or None


@items_bp.route("/create", methods=["POST"])
@login_required
def create_item():
    if not (can("edit_meta") or can("edit_grocery")):
        abort(403)
    hid = household_id()
    name = (request.form.get("name") or "").strip()
    item_type = (request.form.get("item_type") or "custom").strip().lower()
    barcode = (request.form.get("barcode") or "").strip() or None
    if not name:
        flash("Name is required.", "danger")
        return redirect(url_for("items.new_item", barcode=barcode or ""))
    if not can("edit_meta"):
        item_type = "grocery"
    if item_type not in ITEM_TYPES:
        item_type = "custom"
    if barcode:
        exists = Item.query.filter_by(household_id=hid, barcode=barcode).first()
        if exists:
            flash("That barcode is already in this household.", "warning")
            return redirect(url_for("items.detail", item_id=exists.id))
    item = Item(
        household_id=hid,
        name=name,
        item_type=item_type,
        category=(request.form.get("category") or "").strip() or None,
        barcode=barcode,
        notes=(request.form.get("notes") or "").strip() or None,
        created_by=current_user.id,
    )
    tags = (request.form.get("tags") or "").strip()
    if tags:
        item.tags = [t.strip() for t in tags.split(",") if t.strip()]
    db.session.add(item)
    db.session.flush()
    if not item.barcode:
        item.barcode = item_payload(hid, item.id)
    _attach_type_row(item, request.form)
    db.session.commit()
    flash(f"{item.name} saved.", "success")
    return redirect(url_for("items.detail", item_id=item.id))


@items_bp.route("/<int:item_id>")
@login_required
def detail(item_id):
    item = _item_or_404(item_id)
    tab = (request.args.get("tab") or "overview").strip()
    hid = household_id()
    maint = (
        MaintenanceRecord.query.filter_by(household_id=hid, parent_id=item.id)
        .order_by(MaintenanceRecord.date.desc())
        .all()
    )
    history = (
        ScanEvent.query.filter_by(household_id=hid, item_id=item.id)
        .order_by(ScanEvent.created_at.desc())
        .limit(40)
        .all()
    )
    photos = (
        PhotoNote.query.filter_by(household_id=hid, item_id=item.id)
        .order_by(PhotoNote.created_at.desc())
        .all()
    )
    reminders = (
        Reminder.query.filter_by(household_id=hid, linked_item_id=item.id, status="open")
        .order_by(Reminder.due_at.asc())
        .all()
    )
    return render_template(
        "item_detail.html",
        item=item,
        tab=tab,
        maint=maint,
        history=history,
        photos=photos,
        reminders=reminders,
        can_edit=can("edit_meta"),
        can_grocery=can("edit_grocery"),
        can_maintain=can("maintain"),
        can_photo=can("photo"),
    )


@items_bp.route("/<int:item_id>/edit", methods=["POST"])
@login_required
@require_perm("edit_meta")
def edit_item(item_id):
    item = _item_or_404(item_id)
    item.name = (request.form.get("name") or item.name).strip()
    item.category = (request.form.get("category") or "").strip() or None
    item.notes = (request.form.get("notes") or "").strip() or None
    barcode = (request.form.get("barcode") or "").strip() or None
    if barcode:
        clash = (
            Item.query.filter_by(household_id=item.household_id, barcode=barcode)
            .filter(Item.id != item.id)
            .first()
        )
        if clash:
            flash("Barcode already used on another item.", "danger")
            return redirect(url_for("items.detail", item_id=item.id))
        item.barcode = barcode
    tags = (request.form.get("tags") or "").strip()
    item.tags = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    _attach_type_row(item, request.form)
    db.session.commit()
    flash("Saved.", "success")
    return redirect(url_for("items.detail", item_id=item.id, tab="overview"))


@items_bp.route("/<int:item_id>/qty", methods=["POST"])
@login_required
def qty(item_id):
    if not (can("edit_grocery") or can("scan")):
        flash("You cannot change stock.", "warning")
        return redirect(url_for("items.detail", item_id=item_id))
    item = _item_or_404(item_id)
    if item.item_type != "grocery" or not item.grocery:
        return redirect(url_for("items.detail", item_id=item_id))
    action = (request.form.get("action") or "consume").strip().lower()
    amount = request.form.get("amount") or 1
    apply_grocery_stock(item.grocery, item, action, amount, current_user.id)
    db.session.commit()
    flash(f"{item.name} updated.", "success")
    return redirect(url_for("items.detail", item_id=item.id))


@items_bp.route("/<int:item_id>/maintenance", methods=["GET", "POST"])
@login_required
@require_perm("maintain")
def maintenance(item_id):
    item = _item_or_404(item_id)
    if request.method == "GET":
        return render_template("maintenance_form.html", item=item)
    mtype = (request.form.get("type") or "maintenance").strip()
    date_s = (request.form.get("date") or "").strip()
    try:
        date = datetime.strptime(date_s, "%Y-%m-%d").date() if date_s else datetime.utcnow().date()
    except ValueError:
        date = datetime.utcnow().date()
    miles = request.form.get("mileage_or_hours") or None
    rec = MaintenanceRecord(
        household_id=household_id(),
        parent_type=item.item_type,
        parent_id=item.id,
        type=mtype,
        date=date,
        mileage_or_hours=_dec(miles, "0") if miles else None,
        notes=(request.form.get("notes") or "").strip() or None,
        created_by=current_user.id,
    )
    db.session.add(rec)
    if item.tool:
        item.tool.last_maintenance_at = datetime.utcnow()
        if miles:
            item.tool.hours_used = _dec(miles, "0")
        interval = item.tool.maintenance_interval_hours
        if interval:
            db.session.add(
                Reminder(
                    household_id=household_id(),
                    linked_item_id=item.id,
                    type=mtype,
                    title=f"Next {mtype} — {item.name}",
                    due_at=datetime.utcnow() + timedelta(days=max(int(interval), 1)),
                    recurrence=None,
                    status="open",
                    created_by=current_user.id,
                )
            )
    if item.vehicle:
        if miles:
            item.vehicle.current_mileage = int(_dec(miles, "0"))
        if mtype in ("oil_change", "oil change", "oil"):
            item.vehicle.last_oil_change_date = date
            if miles:
                item.vehicle.last_oil_change_mileage = int(_dec(miles, "0"))
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
    flash("Maintenance logged.", "success")
    return redirect(url_for("items.detail", item_id=item.id, tab="maintenance"))


@items_bp.route("/<int:item_id>/photo", methods=["POST"])
@login_required
@require_perm("photo")
def add_photo(item_id):
    item = _item_or_404(item_id)
    f = request.files.get("photo")
    if not f or not f.filename:
        flash("Choose a photo.", "danger")
        return redirect(url_for("items.detail", item_id=item.id, tab="photos"))
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_PHOTO:
        flash("Photo must be jpg, png, webp, or gif.", "danger")
        return redirect(url_for("items.detail", item_id=item.id, tab="photos"))
    hid = household_id()
    folder = os.path.join(_uploads_root(), str(hid), str(item.id))
    os.makedirs(folder, exist_ok=True)
    name = secrets.token_hex(8) + ext
    path = os.path.join(folder, name)
    f.save(path)
    rel = f"{hid}/{item.id}/{name}"
    db.session.add(
        PhotoNote(
            household_id=hid,
            item_id=item.id,
            caption=(request.form.get("caption") or "").strip() or None,
            image_path=rel,
            created_by=current_user.id,
        )
    )
    db.session.commit()
    flash("Photo saved.", "success")
    return redirect(url_for("items.detail", item_id=item.id, tab="photos"))


@items_bp.route("/photo/<int:photo_id>")
@login_required
def serve_photo(photo_id):
    row = scoped(PhotoNote).filter_by(id=photo_id).first_or_404()
    folder = _uploads_root()
    directory = os.path.dirname(os.path.join(folder, row.image_path))
    filename = os.path.basename(row.image_path)
    return send_from_directory(directory, filename)


@items_bp.route("/<int:item_id>/qr.png")
@login_required
def qr_png(item_id):
    item = _item_or_404(item_id)
    payload = ensure_item_barcode(item)
    db.session.commit()
    return qr_png_response(payload, f"{item.name}-qr.png")


@items_bp.route("/<int:item_id>/delete", methods=["POST"])
@login_required
@require_perm("edit_meta")
def delete_item(item_id):
    item = _item_or_404(item_id)
    db.session.delete(item)
    db.session.commit()
    flash("Item removed.", "info")
    return redirect(url_for("home.home"))
