import os
import secrets
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import login_required, current_user
from sqlalchemy import or_

from app.builddb.builddb import db
from app.builddb.table_items import Item, ITEM_TYPES
from app.builddb.table_grocery_items import GroceryItem
from app.builddb.table_tools import Tool
from app.builddb.table_vehicles import Vehicle
from app.builddb.table_maintenance_records import MaintenanceRecord
from app.builddb.table_reminders import Reminder
from app.builddb.table_photo_notes import PhotoNote
from app.builddb.table_scan_events import ScanEvent
from app.builddb.table_notes import Note
from app.builddb.table_users import User
from app.utils.household import household_id, scoped
from app.utils.permissions import can, require_perm
from app.utils.qr_labels import ensure_item_barcode, qr_png_response, item_payload
from app.utils.scan import apply_grocery_stock, flag_need_more, clamp_qty, _dec
from app.utils.crypto import write_encrypted_file, sendable_image

items_bp = Blueprint("items", __name__, url_prefix="/items")

ALLOWED_PHOTO = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".pdf"}


def can_create_type(item_type: str) -> bool:
    item_type = (item_type or "").strip().lower()
    if can("edit_meta"):
        return True
    if item_type == "grocery" and can("edit_grocery"):
        return True
    if item_type in ("tool", "vehicle", "house") and can("maintain"):
        return True
    return False


PHOTO_KINDS = ("photo", "receipt", "serial", "connector")


def save_item_photo(item, upload, caption=None, user_id=None, part_id=None, kind=None, warranty_until=None):
    """Save an encrypted household photo. Returns PhotoNote or None."""
    if not upload or not getattr(upload, "filename", None):
        return None
    ext = os.path.splitext(upload.filename)[1].lower()
    if ext not in ALLOWED_PHOTO:
        return None
    hid = item.household_id
    folder = os.path.join(_uploads_root(), str(hid), str(item.id))
    os.makedirs(folder, exist_ok=True)
    name = secrets.token_hex(8) + ext + ".enc"
    path = os.path.join(folder, name)
    data = upload.read()
    if not data:
        return None
    if len(data) > 20 * 1024 * 1024:
        return None
    write_encrypted_file(path, data)
    kind = (kind or "photo").strip().lower()
    if ext == ".pdf":
        kind = "receipt"
    if kind not in PHOTO_KINDS:
        kind = "photo"
    until = None
    if warranty_until:
        try:
            until = datetime.strptime(str(warranty_until)[:10], "%Y-%m-%d").date()
        except Exception:
            until = None
    row = PhotoNote(
        household_id=hid,
        item_id=item.id,
        part_id=int(part_id) if part_id else None,
        kind=kind,
        caption=(caption or "").strip() or None,
        image_path=f"{hid}/{item.id}/{name}",
        warranty_until=until,
        created_by=user_id,
    )
    db.session.add(row)
    db.session.flush()
    return row


def resolve_photo_file(row) -> Path:
    """Only files under uploads/<household_id>/… . No path traversal."""
    root = Path(_uploads_root()).resolve()
    rel = Path(str(row.image_path or ""))
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        abort(404)
    if rel.parts[0] != str(row.household_id):
        abort(404)
    path = (root / rel).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        abort(404)
    if not path.is_file():
        abort(404)
    return path


def _item_or_404(item_id):
    return scoped(Item).filter_by(id=item_id).first_or_404()


def _uploads_root():
    root = os.path.join(os.path.dirname(current_app.root_path), "uploads")
    os.makedirs(root, exist_ok=True)
    return root


@items_bp.route("/new")
@login_required
def new_item():
    if not (can("edit_meta") or can("edit_grocery") or can("maintain")):
        flash("Ask a household admin to add new items.", "warning")
        abort(403)
    barcode = (request.args.get("barcode") or "").strip()
    suggested = (request.args.get("type") or "grocery").strip().lower()
    if suggested not in ITEM_TYPES:
        suggested = "grocery"
    if not can_create_type(suggested):
        suggested = "grocery" if can("edit_grocery") else ("tool" if can("maintain") else "custom")
    lookup = {}
    if barcode and barcode.replace("-", "").isalnum() and len(barcode) >= 8:
        try:
            from app.utils.barcode_lookup import lookup_upc
            from app.utils.classify import classify
            from app.builddb.table_households import Household

            lookup = lookup_upc(barcode)
            guess = classify(lookup, household=Household.query.get(household_id()), extra=barcode)
            if guess.get("item_type") in ITEM_TYPES and can_create_type(guess["item_type"]):
                suggested = guess["item_type"]
            lookup["kind"] = guess.get("kind")
            lookup["kind_label"] = guess.get("kind_label")
            lookup["message"] = guess.get("message")
            lookup["location_hint"] = guess.get("location_hint")
        except Exception:
            lookup = lookup or {}
    from app.utils.classify import household_anchors

    anchors = household_anchors(household_id())
    return render_template(
        "item_create.html",
        barcode=barcode,
        suggested=suggested,
        lookup=lookup,
        types=[t for t in ITEM_TYPES if can_create_type(t) and t != "house"],
        barcode_optional=True,
        vehicles=anchors["vehicles"],
        tools=anchors["tools"],
    )


def _attach_type_row(item, form):
    hid = item.household_id
    if item.item_type == "grocery":
        g = GroceryItem.query.filter_by(item_id=item.id, household_id=hid).first()
        if g is None:
            g = GroceryItem(item_id=item.id, household_id=hid)
            db.session.add(g)
        g.quantity = clamp_qty(form.get("quantity") or 2, "2")
        g.restock_threshold = clamp_qty(form.get("restock_threshold") or 1, "1")
        g.brand = (form.get("brand") or "").strip() or None
        g.size = (form.get("size") or "").strip() or None
        g.unit = (form.get("unit") or "each").strip() or "each"
        g.default_location = (form.get("default_location") or "").strip() or None
        g.ingredients = (form.get("ingredients") or "").strip() or None
        g.allergens = (form.get("allergens") or "").strip() or None
        g.serving_size = (form.get("serving_size") or "").strip() or None
        g.packaging = (form.get("packaging") or "").strip() or None
        g.image_url = (form.get("image_url") or "").strip() or None
        g.is_in_stock = g.quantity > 0
        g.needs_restock = g.quantity <= g.restock_threshold
        extra = dict(g.extra_data or {}) if isinstance(g.extra_data, dict) else {}
        exp = (form.get("expires_on") or "").strip()
        if exp:
            extra["expires_on"] = exp[:10]
        elif "expires_on" in extra:
            extra.pop("expires_on", None)
        g.extra_data = extra or None
        if form.get("product_facts"):
            extra = dict(g.extra_data or {})
            extra["product"] = extra.get("product") or {}
            g.extra_data = extra
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
        v.vin = (form.get("vin") or "").strip().upper() or None
        v.plate = (form.get("plate") or "").strip().upper() or None
        v.color = (form.get("color") or "").strip() or None
        v.trim = (form.get("trim") or "").strip() or None
        v.body_class = (form.get("body_class") or "").strip() or None
        v.drive_type = (form.get("drive_type") or "").strip() or None
        v.fuel_type = (form.get("fuel_type") or "").strip() or None
        v.engine = (form.get("engine") or "").strip() or None
        v.transmission = (form.get("transmission") or "").strip() or None
        v.doors = (form.get("doors") or "").strip() or None
        v.manufacturer = (form.get("manufacturer") or "").strip() or None
        v.oil_type = (form.get("oil_type") or "").strip() or None
        v.filter_type = (form.get("filter_type") or "").strip() or None
        v.tire_size = (form.get("tire_size") or "").strip() or None
        v.battery_type = (form.get("battery_type") or "").strip() or None
        miles = form.get("current_mileage") or ""
        v.current_mileage = int(miles) if str(miles).isdigit() else None
        v.manual_url = (form.get("manual_url") or "").strip() or None


def quick_create_item(
    *,
    hid: int,
    user_id: int,
    name: str,
    item_type: str = "grocery",
    barcode: str | None = None,
    linked_item_id=None,
    kind: str | None = None,
    kind_label: str | None = None,
    location: str | None = None,
    quantity=None,
    action: str = "check",
    photo=None,
    caption: str | None = None,
):
    """One-tap save from scan. Grocery/tool/vehicle with sane defaults."""
    from app.utils.qr_labels import item_payload
    from app.utils.barcode_lookup import lookup_product, apply_product_lookup
    from app.utils.scan import apply_grocery_stock, flag_need_more, clamp_qty

    name = (name or "").strip()
    if not name:
        return None, "name required"
    item_type = (item_type or "grocery").strip().lower()
    if item_type not in ITEM_TYPES:
        item_type = "grocery"
    barcode = (barcode or "").strip() or None
    if barcode:
        exists = Item.query.filter_by(household_id=hid, barcode=barcode).first()
        if exists:
            return exists, "exists"
    item = Item(
        household_id=hid,
        name=name[:200],
        item_type=item_type,
        barcode=barcode,
        created_by=user_id,
    )
    if linked_item_id:
        try:
            lid = int(linked_item_id)
        except (TypeError, ValueError):
            lid = None
        if lid:
            linked = Item.query.filter_by(household_id=hid, id=lid).first()
            if linked:
                item.linked_item_id = linked.id
    db.session.add(item)
    db.session.flush()
    if not item.barcode:
        item.barcode = item_payload(hid, item.id)
    if item_type == "grocery":
        g = GroceryItem(
            item_id=item.id,
            household_id=hid,
            quantity=0,
            restock_threshold=1,
            is_in_stock=False,
            needs_restock=True,
            default_location=(location or "").strip() or None,
        )
        db.session.add(g)
        db.session.flush()
        if barcode:
            try:
                apply_product_lookup(g, item, lookup_product(barcode))
            except Exception:
                pass
        extra = dict(g.extra_data or {})
        if kind:
            extra["kind"] = str(kind)[:40]
            extra["kind_label"] = str(kind_label or kind)[:80]
            g.extra_data = extra
        if action == "restock":
            apply_grocery_stock(g, item, "restock", quantity or 1, user_id)
        elif action in ("want", "need_more"):
            flag_need_more(g, item, user_id)
    elif item_type == "tool":
        db.session.add(Tool(item_id=item.id, household_id=hid, type=(kind_label or kind or "").strip() or None))
    elif item_type == "vehicle":
        db.session.add(Vehicle(item_id=item.id, household_id=hid))
    if photo is not None:
        save_item_photo(item, photo, caption, user_id)
    if item.linked_item_id and kind:
        try:
            from app.utils.vehicle_systems import attach_scanned_part

            attach_scanned_part(
                hid=hid,
                user_id=user_id,
                vehicle_item_id=item.linked_item_id,
                catalog_item=item,
                kind=kind,
                name=item.name,
                brand=(item.grocery.brand if item.grocery else None),
            )
        except Exception:
            pass
    try:
        from app.builddb.table_households import Household
        from app.utils.places import remember_upc

        if barcode:
            remember_upc(
                Household.query.get(hid),
                barcode,
                {
                    "name": item.name,
                    "item_type": item.item_type,
                    "linked_item_id": item.linked_item_id,
                    "kind": kind,
                    "location": location,
                },
            )
    except Exception:
        pass
    db.session.commit()
    return item, "ok"


def _enrich_from_lookups(item):
    if item.item_type == "grocery" and item.grocery and item.barcode:
        try:
            from app.utils.barcode_lookup import lookup_product, apply_product_lookup

            apply_product_lookup(item.grocery, item, lookup_product(item.barcode))
        except Exception:
            pass
    if item.item_type == "vehicle" and item.vehicle:
        try:
            from app.utils.vehicle_lookup import lookup_vehicle, apply_vehicle_lookup

            decoded = lookup_vehicle(plate=item.vehicle.plate or "", vin=item.vehicle.vin or "")
            if decoded.get("ok"):
                apply_vehicle_lookup(item.vehicle, item, decoded)
        except Exception:
            pass


@items_bp.route("/create", methods=["POST"])
@login_required
def create_item():
    hid = household_id()
    name = (request.form.get("name") or "").strip()
    item_type = (request.form.get("item_type") or "custom").strip().lower()
    barcode = (request.form.get("barcode") or "").strip() or None
    if not name:
        flash("Name is required.", "danger")
        return redirect(url_for("items.new_item", barcode=barcode or "", type=item_type))
    if item_type not in ITEM_TYPES:
        item_type = "custom"
    if not can_create_type(item_type):
        abort(403)
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
    linked_raw = (request.form.get("linked_item_id") or "").strip()
    if linked_raw.isdigit():
        linked = scoped(Item).filter_by(id=int(linked_raw)).first()
        if linked:
            item.linked_item_id = linked.id
    db.session.add(item)
    db.session.flush()
    if not item.barcode:
        item.barcode = item_payload(hid, item.id)
    _attach_type_row(item, request.form)
    _enrich_from_lookups(item)
    save_item_photo(
        item, request.files.get("photo"), request.form.get("caption"), current_user.id
    )
    db.session.commit()
    flash(f"{item.name} saved.", "success")
    return redirect(url_for("items.detail", item_id=item.id))


@items_bp.route("/quick", methods=["POST"])
@login_required
def quick_item():
    if not (can("edit_grocery") or can("edit_meta") or can("maintain")):
        abort(403)
    item_type = (request.form.get("item_type") or "grocery").strip().lower()
    if not can_create_type(item_type):
        abort(403)
    item, status = quick_create_item(
        hid=household_id(),
        user_id=current_user.id,
        name=request.form.get("name") or "",
        item_type=item_type,
        barcode=request.form.get("barcode"),
        linked_item_id=request.form.get("linked_item_id"),
        kind=request.form.get("kind"),
        kind_label=request.form.get("kind_label"),
        location=request.form.get("location") or request.form.get("default_location"),
        quantity=request.form.get("quantity"),
        action=(request.form.get("action") or "check").strip().lower(),
        photo=request.files.get("photo"),
        caption=request.form.get("caption"),
    )
    if item is None:
        flash("Name is required.", "danger")
        return redirect(url_for("scan.scan_page"))
    if status == "exists":
        flash("That barcode is already in this household.", "warning")
        return redirect(url_for("items.detail", item_id=item.id))
    flash(f"{item.name} saved.", "success")
    return redirect(url_for("items.detail", item_id=item.id))


@items_bp.route("/<int:item_id>")
@login_required
def detail(item_id):
    item = _item_or_404(item_id)
    tab = (request.args.get("tab") or "").strip()
    if not tab:
        tab = "systems" if item.item_type in ("vehicle", "house") else "overview"
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
    item_notes = (
        Note.query.filter_by(household_id=hid, item_id=item.id)
        .filter(or_(Note.visibility == "household", Note.user_id == current_user.id))
        .order_by(Note.updated_at.desc())
        .all()
    )
    note_authors = {u.id: u for u in User.query.filter_by(household_id=hid).all()}
    linked = None
    if item.linked_item_id:
        linked = scoped(Item).filter_by(id=item.linked_item_id).first()
    parts = (
        Item.query.filter_by(household_id=hid, linked_item_id=item.id)
        .order_by(Item.name.asc())
        .all()
    )
    kind_label = None
    if item.grocery and isinstance(item.grocery.extra_data, dict):
        kind_label = item.grocery.extra_data.get("kind_label")
    from app.utils.classify import household_anchors

    anchors = household_anchors(hid)
    systems = []
    systems_catalog = []
    part_photos = {}
    systems_host = item.item_type if item.item_type in ("vehicle", "house") else None
    if systems_host:
        from app.builddb.table_vehicle_parts import VehiclePart
        from app.utils.vehicle_systems import (
            group_parts,
            seed_from_vehicle_fields,
            systems_payload,
        )

        if item.item_type == "vehicle":
            seeded = seed_from_vehicle_fields(item)
            if seeded:
                db.session.commit()
        vparts = (
            VehiclePart.query.filter_by(household_id=hid, vehicle_item_id=item.id)
            .order_by(VehiclePart.system.asc(), VehiclePart.slot.asc(), VehiclePart.created_at.desc())
            .all()
        )
        if item.item_type == "house":
            from app.utils.house_systems import group_house_parts, house_systems_payload

            systems = group_house_parts(vparts)
            systems_catalog = house_systems_payload()
        else:
            systems = group_parts(vparts)
            systems_catalog = systems_payload()
        for ph in photos:
            if ph.part_id:
                part_photos.setdefault(ph.part_id, []).append(ph)
    return render_template(
        "item_detail.html",
        item=item,
        tab=tab,
        maint=maint,
        history=history,
        photos=photos,
        reminders=reminders,
        item_notes=item_notes,
        note_authors=note_authors,
        can_edit=can("edit_meta"),
        can_grocery=can("edit_grocery"),
        can_scan=can("scan"),
        can_maintain=can("maintain"),
        can_photo=can("photo"),
        product_facts=((item.grocery.extra_data or {}).get("product") if item.grocery else {}) or {},
        vehicle_facts=((item.vehicle.extra_data or {}).get("nhtsa") if item.vehicle else {}) or {},
        vehicle_recalls=((item.vehicle.extra_data or {}).get("recalls") if item.vehicle else {}) or [],
        linked=linked,
        parts=parts,
        kind_label=kind_label,
        vehicles=anchors["vehicles"],
        tools=anchors["tools"],
        systems=systems,
        systems_catalog=systems_catalog,
        part_photos=part_photos,
        systems_host=systems_host,
        photo_kinds=PHOTO_KINDS,
        expires_on=((item.grocery.extra_data or {}).get("expires_on") if item.grocery and isinstance(item.grocery.extra_data, dict) else None),
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
    linked_raw = (request.form.get("linked_item_id") or "").strip()
    if linked_raw.isdigit():
        linked = scoped(Item).filter_by(id=int(linked_raw)).first()
        item.linked_item_id = linked.id if linked else None
    elif linked_raw in ("", "0"):
        item.linked_item_id = None
    _attach_type_row(item, request.form)
    if (request.form.get("lookup_now") or "").strip():
        _enrich_from_lookups(item)
    db.session.commit()
    flash("Saved.", "success")
    return redirect(url_for("items.detail", item_id=item.id, tab="overview"))


@items_bp.route("/<int:item_id>/lookup", methods=["POST"])
@login_required
def lookup_again(item_id):
    if not (can("edit_meta") or can("edit_grocery") or can("scan")):
        abort(403)
    item = _item_or_404(item_id)
    _enrich_from_lookups(item)
    db.session.commit()
    flash("Looked up full details.", "success")
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
    if action in ("need_more", "needs_more"):
        stock = flag_need_more(item.grocery, item, current_user.id)
    else:
        stock = apply_grocery_stock(item.grocery, item, action, amount, current_user.id)
    db.session.commit()
    cat = "success" if stock.get("status") == "ok" else "warning"
    flash(stock.get("message") or f"{item.name} updated.", cat)
    return redirect(url_for("items.detail", item_id=item.id))


def _parse_day(raw: str):
    s = (raw or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return None


def _follow_up_from_maintenance(item, mtype, date, miles, form) -> Reminder | None:
    """Next due from the form, else oil/tool interval. None if they left it blank."""
    from app.utils.reminders_copy import parse_recurrence

    due = _parse_day(form.get("next_due") if form is not None else "")
    rec = parse_recurrence((form or {}).get("recurrence")) if form is not None else None
    title = (form.get("next_title") or "").strip() if form is not None else ""
    if due is None and item.tool:
        interval = item.tool.maintenance_interval_hours
        if interval:
            due = datetime.utcnow() + timedelta(days=max(int(interval), 1))
            title = title or f"Next {mtype} — {item.name}"
    oil = (mtype or "").strip().lower() in ("oil_change", "oil change", "oil")
    if due is None and item.vehicle and oil:
        due = datetime.utcnow() + timedelta(days=180)
        rec = rec or "180d"
        title = title or f"Next oil change — {item.name}"
    if due is None:
        return None
    if not title:
        title = f"Next {mtype} — {item.name}"
    return Reminder(
        household_id=household_id(),
        linked_item_id=item.id,
        type="oil_change" if oil else (mtype or "maintenance"),
        title=title[:200],
        due_at=due,
        recurrence=rec,
        status="open",
        created_by=current_user.id,
    )


@items_bp.route("/<int:item_id>/maintenance", methods=["GET", "POST"])
@login_required
@require_perm("maintain")
def maintenance(item_id):
    item = _item_or_404(item_id)
    if request.method == "GET":
        from app.utils.calendar import calendar_target

        return render_template(
            "maintenance_form.html",
            item=item,
            cal=calendar_target(current_user),
        )
    mtype = (request.form.get("type") or "maintenance").strip()
    date_s = (request.form.get("date") or "").strip()
    try:
        date = datetime.strptime(date_s, "%Y-%m-%d").date() if date_s else datetime.utcnow().date()
    except ValueError:
        date = datetime.utcnow().date()
    miles = request.form.get("mileage_or_hours") or None
    new_reminders = []
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
    db.session.flush()
    photo_ids = []
    files = request.files.getlist("photo") or []
    if not files:
        one = request.files.get("photo")
        files = [one] if one else []
    for upload in files:
        row = save_item_photo(
            item,
            upload,
            request.form.get("caption") or mtype,
            current_user.id,
        )
        if row:
            photo_ids.append(row.id)
    if photo_ids:
        rec.photos = photo_ids
    if item.tool:
        item.tool.last_maintenance_at = datetime.utcnow()
        if miles:
            item.tool.hours_used = _dec(miles, "0")
    if item.vehicle:
        if miles:
            item.vehicle.current_mileage = int(_dec(miles, "0"))
        if mtype in ("oil_change", "oil change", "oil"):
            item.vehicle.last_oil_change_date = date
            if miles:
                item.vehicle.last_oil_change_mileage = int(_dec(miles, "0"))
    rem = _follow_up_from_maintenance(item, mtype, date, miles, request.form)
    if rem is not None:
        db.session.add(rem)
        new_reminders.append(rem)
    db.session.commit()
    from app.utils.notify import announce_flash, announce_reminder

    for follow in new_reminders:
        announce_reminder(follow)
    note = announce_flash(current_user, new_reminders[0] if new_reminders else None)
    flash(note or "Maintenance logged.", "success")
    return redirect(url_for("items.detail", item_id=item.id, tab="maintenance"))


@items_bp.route("/<int:item_id>/photo", methods=["POST"])
@login_required
@require_perm("photo")
def add_photo(item_id):
    item = _item_or_404(item_id)
    f = request.files.get("photo")
    kind = (request.form.get("kind") or "photo").strip().lower()
    warranty = (request.form.get("warranty_until") or "").strip()
    row = save_item_photo(
        item,
        f,
        request.form.get("caption"),
        current_user.id,
        kind=kind,
        warranty_until=warranty,
    )
    if not row:
        flash("Choose a jpg, png, webp, or gif.", "danger")
        return redirect(url_for("items.detail", item_id=item.id, tab="photos"))
    if row.warranty_until:
        rem = Reminder(
            household_id=household_id(),
            linked_item_id=item.id,
            type="custom",
            title=f"Warranty — {item.name}",
            due_at=datetime.combine(row.warranty_until, datetime.min.time()),
            status="open",
            created_by=current_user.id,
        )
        db.session.add(rem)
        db.session.commit()
        from app.utils.notify import announce_reminder

        announce_reminder(rem)
    else:
        db.session.commit()
    flash("Photo saved.", "success")
    nxt = (request.form.get("next") or "photos").strip() or "photos"
    if nxt not in ("overview", "photos", "notes", "maintenance", "history", "systems"):
        nxt = "photos"
    return redirect(url_for("items.detail", item_id=item.id, tab=nxt))


@items_bp.route("/photo/<int:photo_id>")
@login_required
def serve_photo(photo_id):
    row = scoped(PhotoNote).filter_by(id=photo_id).first_or_404()
    path = resolve_photo_file(row)
    ext = os.path.splitext(str(path.name).replace(".enc", ""))[1].lower()
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".pdf": "application/pdf",
    }.get(ext, "application/octet-stream")
    return sendable_image(path, mime)


def attach_part_uploads(item, part, user_id=None):
    """Photo of the part and/or a receipt (image or PDF). Returns how many saved."""
    if part is None:
        return 0
    saved = 0
    photo = request.files.get("photo")
    if photo and getattr(photo, "filename", None):
        row = save_item_photo(
            item,
            photo,
            request.form.get("caption") or part.name,
            user_id,
            part_id=part.id,
            kind="photo",
        )
        if row:
            saved += 1
    receipt = request.files.get("receipt")
    if receipt and getattr(receipt, "filename", None):
        row = save_item_photo(
            item,
            receipt,
            request.form.get("receipt_caption") or "Receipt",
            user_id,
            part_id=part.id,
            kind="receipt",
            warranty_until=request.form.get("warranty_until"),
        )
        if row:
            saved += 1
    return saved


def _part_shop_fields():
    return {
        "source": (request.form.get("source") or "").strip()[:200] or None,
        "cost": request.form.get("cost"),
        "warranty_until": request.form.get("warranty_until"),
        "notes": (request.form.get("notes") or "").strip() or None,
    }


@items_bp.route("/<int:item_id>/qr.png")
@login_required
def qr_png(item_id):
    item = _item_or_404(item_id)
    payload = ensure_item_barcode(item)
    db.session.commit()
    return qr_png_response(payload, f"{item.name}-qr.png")


@items_bp.route("/labels")
@login_required
def labels():
    hid = household_id()
    rows = (
        Item.query.filter_by(household_id=hid)
        .filter(Item.item_type.in_(("tool", "vehicle", "house", "custom")))
        .order_by(Item.item_type.asc(), Item.name.asc())
        .all()
    )
    for item in rows:
        ensure_item_barcode(item)
    db.session.commit()
    return render_template("labels.html", items=rows)


@items_bp.route("/<int:item_id>/mileage", methods=["POST"])
@login_required
def set_mileage(item_id):
    if not (can("scan") or can("maintain") or can("edit_meta")):
        abort(403)
    item = _item_or_404(item_id)
    raw = (request.form.get("mileage") or request.form.get("hours") or "").replace(",", "").strip()
    if item.item_type == "vehicle" and item.vehicle:
        try:
            item.vehicle.current_mileage = int(raw)
        except Exception:
            flash("Type the miles as a number.", "danger")
            return redirect(url_for("items.detail", item_id=item.id))
        db.session.commit()
        flash(f"{item.name} is at {item.vehicle.current_mileage:,} miles.", "success")
    elif item.item_type == "tool" and item.tool:
        try:
            item.tool.hours_used = _dec(raw, "0")
        except Exception:
            flash("Type the hours as a number.", "danger")
            return redirect(url_for("items.detail", item_id=item.id))
        db.session.commit()
        flash(f"{item.name} is at {item.tool.hours_used} hours.", "success")
    else:
        abort(404)
    nxt = (request.form.get("next") or "").strip()
    if nxt == "scan":
        return redirect(url_for("scan.scan_page"))
    return redirect(url_for("items.detail", item_id=item.id, tab="overview"))


@items_bp.route("/<int:item_id>/parts", methods=["POST"])
@login_required
def add_part(item_id):
    if not (can("maintain") or can("edit_meta")):
        abort(403)
    item = _item_or_404(item_id)
    if item.item_type not in ("vehicle", "house"):
        abort(404)
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Name the part.", "danger")
        return redirect(url_for("items.detail", item_id=item.id, tab="systems"))
    hid = household_id()
    if item.item_type == "house":
        from app.utils.house_systems import HOUSE_SLOTS, install_house_part
        from app.utils.vehicle_systems import valid_slot, valid_system

        system = valid_system(request.form.get("system"), HOUSE_SLOTS)
        slot = valid_slot(system, request.form.get("slot"), HOUSE_SLOTS)
        row = install_house_part(
            hid=hid,
            vehicle_item_id=item.id,
            user_id=current_user.id,
            system=system,
            slot=slot,
            name=name,
            brand=request.form.get("brand"),
            spec=request.form.get("spec"),
            part_number=request.form.get("part_number"),
            status=(request.form.get("status") or "installed").strip().lower(),
            installed_on=request.form.get("installed_on"),
            installed_mileage=request.form.get("installed_mileage"),
            replace_current=(request.form.get("status") or "installed").strip().lower() == "installed",
            **_part_shop_fields(),
        )
    else:
        from app.utils.vehicle_systems import install_part, valid_slot, valid_system

        system = valid_system(request.form.get("system"))
        slot = valid_slot(system, request.form.get("slot"))
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
            status=(request.form.get("status") or "installed").strip().lower(),
            installed_on=request.form.get("installed_on"),
            installed_mileage=request.form.get("installed_mileage")
            or (item.vehicle.current_mileage if item.vehicle else None),
            replace_current=(request.form.get("status") or "installed").strip().lower() == "installed",
            **_part_shop_fields(),
        )
    nfiles = attach_part_uploads(item, row, current_user.id)
    db.session.commit()
    extra = f" {nfiles} file(s)." if nfiles else ""
    flash(f"{name} saved on {item.name}.{extra}", "success")
    return redirect(url_for("items.detail", item_id=item.id, tab="systems") + f"#sys-{row.system if row else ''}")


@items_bp.route("/<int:item_id>/parts/<int:part_id>/retire", methods=["POST"])
@login_required
def retire_part(item_id, part_id):
    if not (can("maintain") or can("edit_meta")):
        abort(403)
    item = _item_or_404(item_id)
    from app.builddb.table_vehicle_parts import VehiclePart

    row = (
        VehiclePart.query.filter_by(
            id=part_id, household_id=household_id(), vehicle_item_id=item.id
        ).first_or_404()
    )
    row.is_current = False
    row.status = "retired"
    db.session.commit()
    flash(f"{row.name} moved to history.", "info")
    return redirect(url_for("items.detail", item_id=item.id, tab="systems") + f"#sys-{row.system}")


@items_bp.route("/<int:item_id>/parts/<int:part_id>/edit", methods=["POST"])
@login_required
def edit_part(item_id, part_id):
    if not (can("maintain") or can("edit_meta")):
        abort(403)
    item = _item_or_404(item_id)
    from app.builddb.table_vehicle_parts import VehiclePart
    from app.utils.vehicle_systems import parse_cost, parse_day

    row = (
        VehiclePart.query.filter_by(
            id=part_id, household_id=household_id(), vehicle_item_id=item.id
        ).first_or_404()
    )
    name = (request.form.get("name") or "").strip()
    if name:
        row.name = name[:200]
    if "brand" in request.form:
        row.brand = (request.form.get("brand") or "").strip()[:120] or None
    if "spec" in request.form:
        row.spec = (request.form.get("spec") or "").strip()[:160] or None
    if "part_number" in request.form:
        row.part_number = (request.form.get("part_number") or "").strip()[:80] or None
    row.notes = (request.form.get("notes") or "").strip() or None
    row.source = (request.form.get("source") or "").strip()[:200] or None
    if "cost" in request.form:
        row.cost = parse_cost(request.form.get("cost"))
    if "warranty_until" in request.form:
        row.warranty_until = parse_day(request.form.get("warranty_until"))
    if request.form.get("installed_on"):
        row.installed_on = parse_day(request.form.get("installed_on"))
    miles = (request.form.get("installed_mileage") or "").replace(",", "").strip()
    if miles:
        try:
            row.installed_mileage = int(miles)
        except Exception:
            pass
    nfiles = attach_part_uploads(item, row, current_user.id)
    db.session.commit()
    flash(f"{row.name} updated." + (f" {nfiles} file(s)." if nfiles else ""), "success")
    return redirect(url_for("items.detail", item_id=item.id, tab="systems") + f"#sys-{row.system}")


@items_bp.route("/<int:item_id>/delete", methods=["POST"])
@login_required
@require_perm("edit_meta")
def delete_item(item_id):
    item = _item_or_404(item_id)
    db.session.delete(item)
    db.session.commit()
    flash("Item removed.", "info")
    return redirect(url_for("home.home"))
