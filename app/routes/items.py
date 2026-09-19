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
from sqlalchemy.orm import selectinload

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
from app.utils.stay import list_url_for_item, same_site_path, stay_path
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


def save_item_photo(
    item, upload, caption=None, user_id=None, part_id=None, kind=None, warranty_until=None, log_id=None
):
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
        log_id=int(log_id) if log_id else None,
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


def _parts_sheet_url(item, system="", part_id=None, add=False):
    kwargs = {"item_id": item.id}
    if system:
        kwargs["system"] = system
    if part_id:
        kwargs["part"] = part_id
    if add:
        kwargs["add"] = 1
    return url_for("items.parts_sheet", **kwargs)


def _calm_systems_flag() -> bool:
    from app.utils.vehicle_systems import calm_systems

    return calm_systems()


def _want_replace(status: str, *, house: bool = False) -> bool:
    if (status or "").strip().lower() != "installed":
        return False
    vals = request.form.getlist("replace_current")
    if not vals:
        return not house
    return str(vals[-1]).strip().lower() not in ("0", "false", "off", "no")


def _after_part_change(item, system="", part_id=None):
    if (request.form.get("next") or "").strip() == "sheet":
        return redirect(_parts_sheet_url(item, system, part_id=part_id))
    return redirect(url_for("items.detail", item_id=item.id, tab="systems") + (f"#sys-{system}" if system else ""))


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
        g.auto_basket = str(form.get("auto_basket") or "").strip() in ("1", "true", "on", "yes")
        g.is_in_stock = g.quantity > 0
        g.needs_restock = g.quantity <= g.restock_threshold
        extra = dict(g.extra_data or {}) if isinstance(g.extra_data, dict) else {}
        exp = (form.get("expires_on") or "").strip()
        if exp:
            extra["expires_on"] = exp[:10]
            extra.pop("expires_guessed", None)
            extra.pop("expires_cleared", None)
            g.extra_data = extra
        elif extra.get("expires_on"):
            extra.pop("expires_on", None)
            extra["expires_cleared"] = True
            extra.pop("expires_guessed", None)
            g.extra_data = extra or None
        else:
            g.extra_data = extra or None
            from app.utils.shelf_life import apply_shelf_life

            apply_shelf_life(item, g)
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
        if not g.default_location:
            try:
                from app.builddb.table_households import Household
                from app.utils.classify import place_new_grocery
                from app.utils.barcode_lookup import lookup_product

                place_new_grocery(
                    item,
                    g,
                    lookup_product(barcode) if barcode else {"name": name},
                    Household.query.get(hid),
                )
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
    try:
        from app.utils.barcode_lookup import is_placeholder_name
        from app.utils.scan import fill_placeholder_names

        if is_placeholder_name(item.name) and item.barcode and item.grocery:
            fill_placeholder_names([item], limit=1, force=True)
            db.session.commit()
    except Exception:
        db.session.rollback()
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
    item_logs = []
    log_stats = {}
    log_photos = {}
    if item.item_type in ("vehicle", "tool", "house"):
        from app.builddb.table_item_logs import ItemLog
        from app.utils.item_log import log_stats as _log_stats

        item_logs = (
            ItemLog.query.filter_by(household_id=hid, item_id=item.id)
            .order_by(ItemLog.happened_on.desc(), ItemLog.id.desc())
            .limit(80)
            .all()
        )
        log_stats = _log_stats(item)
        for ph in photos:
            if getattr(ph, "log_id", None):
                log_photos.setdefault(ph.log_id, []).append(ph)
    reminders = (
        Reminder.query.filter_by(household_id=hid, linked_item_id=item.id, status="open")
        .order_by(Reminder.due_at.asc())
        .all()
    )
    item_notes = (
        Note.query.options(selectinload(Note.files))
        .filter_by(household_id=hid, item_id=item.id)
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
    on_it_now, on_it_total = [], 0
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
        from app.utils.vehicle_systems import overview_on_it as _overview_on_it

        on_it_now, on_it_total = _overview_on_it(systems)
        for ph in photos:
            if ph.part_id:
                part_photos.setdefault(ph.part_id, []).append(ph)
    stay = same_site_path(request.args.get("next"))
    if not stay:
        ref = same_site_path(request.referrer)
        if ref and not ref.split("?", 1)[0].rstrip("/").endswith(f"/items/{item.id}"):
            stay = ref
    if not stay:
        stay = list_url_for_item(item)
    return render_template(
        "item_detail.html",
        item=item,
        tab=tab,
        stay=stay,
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
        expires_guessed=bool((item.grocery.extra_data or {}).get("expires_guessed")) if item.grocery and isinstance(item.grocery.extra_data, dict) else False,
        last_part_source=((item.extra_data or {}).get("last_part_source") if isinstance(item.extra_data, dict) else None),
        calm_systems=_calm_systems_flag(),
        on_it_now=on_it_now,
        on_it_total=on_it_total,
        item_logs=item_logs,
        log_stats=log_stats,
        log_photos=log_photos,
        today=datetime.utcnow().date().isoformat(),
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


@items_bp.route("/<int:item_id>/rooms", methods=["POST"])
@login_required
def set_rooms(item_id):
    from flask import jsonify

    from app.utils.places import sync_rooms

    if not (can("edit_grocery") or can("scan")):
        abort(403)
    item = _item_or_404(item_id)
    if item.item_type != "grocery" or not item.grocery:
        abort(400)
    payload = request.get_json(silent=True) or {}
    rooms = payload.get("rooms") if isinstance(payload.get("rooms"), dict) else {}
    if not rooms:
        for key, val in request.form.items():
            if key.startswith("room__"):
                rooms[key[6:].replace("_", " ")] = val
            elif key.startswith("room[") and key.endswith("]"):
                rooms[key[5:-1]] = val
    extra_place = (request.form.get("new_place") or payload.get("new_place") or "").strip()
    extra_qty = request.form.get("new_qty") or payload.get("new_qty")
    if extra_place and extra_qty not in (None, ""):
        rooms[extra_place] = extra_qty
    sync_rooms(item.grocery, rooms)
    db.session.commit()
    if request.is_json or request.headers.get("X-Requested-With") == "fetch":
        from app.utils.places import rooms_map
        from app.utils.scan import qty_label

        return jsonify(
            {
                "ok": True,
                "quantity": float(item.grocery.quantity or 0),
                "quantity_label": qty_label(item.grocery.quantity),
                "rooms": {k: float(v) for k, v in rooms_map(item.grocery).items()},
            }
        )
    flash(f"{item.name}: {item.grocery.quantity:g} in the house.", "success")
    return redirect(url_for("items.detail", item_id=item.id, tab="overview"))


@items_bp.route("/<int:item_id>/count", methods=["POST"])
@login_required
@require_perm("override")
def set_count(item_id):
    from app.utils.activity import set_item_qty

    item = _item_or_404(item_id)
    ok, msg = set_item_qty(item, request.form.get("quantity") or 0, user_id=current_user.id)
    flash(msg, "success" if ok else "danger")
    nxt = (request.form.get("next") or "").strip()
    if nxt == "happened":
        return redirect(url_for("members.happened"))
    return redirect(url_for("items.detail", item_id=item.id))


@items_bp.route("/<int:item_id>/qty", methods=["POST"])
@login_required
def qty(item_id):
    from flask import jsonify

    wants_json = (
        request.is_json
        or (request.headers.get("X-Requested-With") or "") in ("fetch", "XMLHttpRequest")
        or (request.headers.get("Accept") or "").find("application/json") >= 0
    )
    if not (can("edit_grocery") or can("scan")):
        if wants_json:
            return jsonify({"ok": False, "error": "You cannot change stock."}), 403
        flash("You cannot change stock.", "warning")
        return redirect(url_for("items.detail", item_id=item_id))
    item = _item_or_404(item_id)
    if item.item_type != "grocery" or not item.grocery:
        if wants_json:
            return jsonify({"ok": False, "error": "Not a grocery."}), 400
        return redirect(url_for("items.detail", item_id=item_id))
    payload = request.get_json(silent=True) or {}
    action = (payload.get("action") or request.form.get("action") or "consume").strip().lower()
    amount = payload.get("amount") if payload.get("amount") is not None else request.form.get("amount") or 1
    place = (payload.get("place") or request.form.get("place") or "").strip() or None
    remember = True
    if action in ("plus", "add", "inc"):
        action = "restock"
        remember = False
    elif action in ("minus", "sub", "dec"):
        action = "consume"
        remember = False
    if action in ("need_more", "needs_more"):
        stock = flag_need_more(item.grocery, item, current_user.id)
    elif action in ("freeze", "fridge", "freezer"):
        from app.utils.shelf_life import set_meat_storage

        frozen = action in ("freeze", "freezer")
        exp = set_meat_storage(item, item.grocery, frozen=frozen)
        stock = {
            "status": "ok",
            "message": (
                f"{item.name} in the {'freezer' if frozen else 'fridge'}."
                + (f" Use by {exp}." if exp else "")
            ),
        }
    else:
        stock = apply_grocery_stock(
            item.grocery, item, action, amount, current_user.id, remember=remember, place=place
        )
    db.session.commit()
    if wants_json:
        return jsonify(
            {
                "ok": True,
                "item_id": item.id,
                "quantity": stock.get("quantity"),
                "quantity_label": stock.get("quantity_label"),
                "status": stock.get("status"),
                "needs_restock": stock.get("needs_restock"),
                "is_in_stock": stock.get("is_in_stock"),
                "on_list": stock.get("on_list"),
                "rooms": stock.get("rooms"),
                "message": stock.get("message"),
            }
        )
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
    try:
        from app.utils.item_log import add_item_log

        add_item_log(
            item,
            kind="repair",
            user_id=current_user.id,
            reading=miles,
            notes=(request.form.get("notes") or "").strip() or None,
            title=mtype,
            happened_on=date,
            maintenance_id=rec.id,
        )
    except Exception:
        pass
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
    notes = (request.form.get("part_notes") or request.form.get("notes") or "").strip() or None
    return {
        "source": (request.form.get("source") or "").strip()[:200] or None,
        "cost": request.form.get("cost"),
        "warranty_until": request.form.get("warranty_until"),
        "notes": notes,
        "model": (request.form.get("model") or "").strip()[:120] or None,
        "serial_number": (request.form.get("serial_number") or request.form.get("serial") or "").strip()[:120] or None,
        "asset_id": (request.form.get("asset_id") or "").strip()[:80] or None,
        "part_number": (request.form.get("part_number") or "").strip()[:80] or None,
    }


def _remember_part_source(item, source: str | None) -> None:
    src = (source or "").strip()[:200]
    if not src:
        return
    extra = dict(item.extra_data) if isinstance(item.extra_data, dict) else {}
    extra["last_part_source"] = src
    item.extra_data = extra
    try:
        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(item, "extra_data")
    except Exception:
        pass


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


@items_bp.route("/<int:item_id>/log", methods=["POST"])
@login_required
def add_log(item_id):
    if not (can("scan") or can("maintain") or can("edit_meta") or can("photo")):
        abort(403)
    item = _item_or_404(item_id)
    if item.item_type not in ("vehicle", "tool", "house"):
        abort(404)
    from app.builddb.table_item_logs import LOG_KINDS
    from app.utils.item_log import add_item_log

    kind = (request.form.get("kind") or "note").strip().lower()
    if kind not in LOG_KINDS:
        kind = "note"
    if kind == "miles" and item.item_type != "vehicle":
        kind = "hours" if item.item_type == "tool" else "note"
    if kind == "hours" and item.item_type != "tool":
        kind = "miles" if item.item_type == "vehicle" else "note"
    happened = _parse_day(request.form.get("happened_on") or "") or datetime.utcnow().date()
    extra = {}
    station = (request.form.get("station") or "").strip()[:120]
    if station:
        extra["station"] = station
    octane = (request.form.get("octane") or "").strip()[:20]
    if octane:
        extra["octane"] = octane
    reading = request.form.get("reading") or request.form.get("mileage") or request.form.get("hours")
    title = request.form.get("title") or request.form.get("type") or request.form.get("code")
    if kind == "code":
        from app.builddb.table_households import Household
        from app.utils.dtc import lookup_dtc, parse_dtcs

        blob = " ".join(filter(None, [title, request.form.get("notes"), request.form.get("code")]))
        codes = parse_dtcs(blob)
        if not codes and (title or "").strip():
            codes = [(title or "").strip().upper()[:12]]
        if not codes:
            flash("Type a code like P0420.", "danger")
            return redirect(url_for("items.detail", item_id=item.id, tab="log"))
        household = Household.query.get(item.household_id)
        status = (request.form.get("code_status") or "active").strip().lower()
        if status not in ("active", "pending", "cleared"):
            status = "active"
        last = None
        for code in codes:
            info = lookup_dtc(code, vehicle=item.vehicle, household=household)
            payload = dict(extra)
            payload.update(info)
            payload["code"] = code
            payload["status"] = status
            last = add_item_log(
                item,
                kind="code",
                user_id=current_user.id,
                reading=reading,
                notes=request.form.get("notes") or request.form.get("body"),
                title=code,
                happened_on=happened,
                extra=payload,
            )
        row = last
        files = request.files.getlist("photo") or []
        if not files:
            one = request.files.get("photo")
            files = [one] if one else []
        for upload in files:
            save_item_photo(
                item,
                upload,
                request.form.get("caption") or (row.title if row else None),
                current_user.id,
                kind="photo",
                log_id=row.id if row else None,
            )
        db.session.commit()
        used = (row.extra_data or {}).get("used_ai") if row and isinstance(row.extra_data, dict) else False
        flash(
            ("Looked up " if used else "Logged ")
            + ", ".join(codes)
            + ("." if used else ". Turn AI on in Household to explain the code."),
            "success",
        )
        return redirect(url_for("items.detail", item_id=item.id, tab="log"))
    row = add_item_log(
        item,
        kind=kind,
        user_id=current_user.id,
        reading=reading,
        gallons=request.form.get("gallons"),
        cost=request.form.get("cost"),
        notes=request.form.get("notes") or request.form.get("body"),
        title=title,
        happened_on=happened,
        extra=extra or None,
    )
    files = request.files.getlist("photo") or []
    if not files:
        one = request.files.get("photo")
        files = [one] if one else []
    for upload in files:
        save_item_photo(
            item,
            upload,
            request.form.get("caption") or (row.title if row else None),
            current_user.id,
            kind="receipt" if kind == "fillup" else "photo",
            log_id=row.id if row else None,
        )
    db.session.commit()
    if kind == "fillup":
        extra_mpg = (row.extra_data or {}).get("mpg") if row and isinstance(row.extra_data, dict) else None
        msg = f"Fill-up on {item.name}."
        if extra_mpg:
            msg = f"Fill-up · {extra_mpg:g} mpg."
        flash(msg, "success")
    elif kind in ("miles", "hours"):
        unit = "miles" if kind == "miles" else "hours"
        flash(f"{item.name} is at {row.reading:g} {unit}." if row and row.reading is not None else "Logged.", "success")
    else:
        flash("Saved to the log.", "success")
    return redirect(url_for("items.detail", item_id=item.id, tab="log"))


@items_bp.route("/<int:item_id>/mileage", methods=["POST"])
@login_required
def set_mileage(item_id):
    if not (can("scan") or can("maintain") or can("edit_meta")):
        abort(403)
    item = _item_or_404(item_id)
    raw = (request.form.get("mileage") or request.form.get("hours") or "").replace(",", "").strip()
    from app.utils.item_log import add_item_log

    if item.item_type == "vehicle" and item.vehicle:
        try:
            miles = int(raw)
        except Exception:
            flash("Type the miles as a number.", "danger")
            return redirect(url_for("items.detail", item_id=item.id))
        item.vehicle.current_mileage = miles
        add_item_log(item, kind="miles", user_id=current_user.id, reading=miles)
        db.session.commit()
        flash(f"{item.name} is at {item.vehicle.current_mileage:,} miles.", "success")
    elif item.item_type == "tool" and item.tool:
        try:
            hours = _dec(raw, "0")
        except Exception:
            flash("Type the hours as a number.", "danger")
            return redirect(url_for("items.detail", item_id=item.id))
        item.tool.hours_used = hours
        add_item_log(item, kind="hours", user_id=current_user.id, reading=hours)
        db.session.commit()
        flash(f"{item.name} is at {item.tool.hours_used} hours.", "success")
    else:
        abort(404)
    nxt = (request.form.get("next") or "").strip()
    if nxt == "scan":
        return redirect(url_for("scan.scan_page"))
    if nxt == "log":
        return redirect(url_for("items.detail", item_id=item.id, tab="log"))
    return redirect(url_for("items.detail", item_id=item.id, tab="overview"))


def _load_systems(item):
    hid = household_id()
    from app.builddb.table_vehicle_parts import VehiclePart
    from app.utils.vehicle_systems import group_parts, systems_payload

    vparts = (
        VehiclePart.query.filter_by(household_id=hid, vehicle_item_id=item.id)
        .order_by(VehiclePart.system.asc(), VehiclePart.slot.asc(), VehiclePart.created_at.desc())
        .all()
    )
    if item.item_type == "house":
        from app.utils.house_systems import group_house_parts, house_systems_payload

        return group_house_parts(vparts), house_systems_payload()
    return group_parts(vparts), systems_payload()


@items_bp.route("/<int:item_id>/systems-ui")
@login_required
def systems_ui(item_id):
    from datetime import timedelta

    from app.utils.vehicle_systems import COOKIE as _sys_cookie

    item = _item_or_404(item_id)
    mode = (request.args.get("mode") or "calm").strip().lower()
    if mode not in ("calm", "classic"):
        mode = "calm"
    resp = redirect(url_for("items.detail", item_id=item.id, tab="systems"))
    resp.set_cookie(
        _sys_cookie,
        mode,
        max_age=int(timedelta(days=400).total_seconds()),
        samesite="Lax",
        httponly=False,
    )
    return resp


@items_bp.route("/<int:item_id>/parts/sheet")
@login_required
def parts_sheet(item_id):
    from datetime import date

    item = _item_or_404(item_id)
    if item.item_type not in ("vehicle", "house"):
        abort(404)
    systems, systems_catalog = _load_systems(item)
    want = (request.args.get("system") or "").strip()
    picked = [s for s in systems if s["id"] == want]
    shown = picked[0] if picked else None
    focus_id = (request.args.get("part") or "").strip()
    focus = None
    if shown and focus_id:
        for p in (shown.get("current") or []) + (shown.get("history") or []):
            if str(getattr(p, "id", "")) == str(focus_id):
                focus = p
                break
    open_add = (request.args.get("add") or "").strip().lower() in ("1", "yes", "true")
    add_slot = (request.args.get("slot") or "").strip()
    part_photos = {}
    for ph in PhotoNote.query.filter_by(household_id=household_id(), item_id=item.id).all():
        if ph.part_id:
            part_photos.setdefault(ph.part_id, []).append(ph)
    current_map = {}
    for s in systems:
        for p in s.get("on_it") or []:
            key = f"{s['id']}:{p.slot}"
            current_map.setdefault(key, []).append({"id": p.id, "name": p.name})
    tmpl = "items/parts_sheet.html" if _calm_systems_flag() else "items/parts_sheet_classic.html"
    return render_template(
        tmpl,
        item=item,
        systems=systems,
        systems_catalog=systems_catalog,
        shown=shown,
        want=want,
        part_photos=part_photos,
        systems_host=item.item_type,
        can_edit=can("edit_meta"),
        can_maintain=can("maintain"),
        last_part_source=((item.extra_data or {}).get("last_part_source") if isinstance(item.extra_data, dict) else None),
        part_next="sheet",
        today=date.today().isoformat(),
        current_map=current_map,
        calm_systems=_calm_systems_flag(),
        focus=focus,
        open_add=open_add,
        add_slot=add_slot,
    )


@items_bp.route("/<int:item_id>/parts", methods=["POST"])
@login_required
def add_part(item_id):
    if not (can("maintain") or can("edit_meta")):
        abort(403)
    item = _item_or_404(item_id)
    if item.item_type not in ("vehicle", "house"):
        abort(404)
    name = (request.form.get("name") or "").strip()
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
            status=(request.form.get("status") or "installed").strip().lower(),
            installed_on=request.form.get("installed_on"),
            installed_mileage=request.form.get("installed_mileage"),
            replace_current=_want_replace(
                (request.form.get("status") or "installed"), house=True
            ),
            **_part_shop_fields(),
        )
    else:
        from app.utils.vehicle_systems import install_part, valid_slot, valid_system

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
            status=status,
            installed_on=request.form.get("installed_on"),
            installed_mileage=request.form.get("installed_mileage")
            or (item.vehicle.current_mileage if item.vehicle else None),
            replace_current=_want_replace(status),
            **_part_shop_fields(),
        )
    nfiles = attach_part_uploads(item, row, current_user.id)
    if not nfiles and row:
        try:
            from app.utils.stash_image import stash_part_picture

            if stash_part_picture(item, row, current_user.id):
                nfiles = 1
        except Exception:
            pass
    _remember_part_source(item, request.form.get("source"))
    extra = f" {nfiles} file(s)." if nfiles else ""
    shown = (row.name if row else name) or "Part"
    try:
        from app.utils.activity import record

        if row:
            record(
                action="part.add",
                summary=f"{current_user.name or current_user.username} put {shown} on {item.name}",
                target_table="vehicle_parts",
                target_id=row.id,
                item_id=item.id,
                new_json={"name": shown, "system": row.system, "slot": row.slot},
            )
    except Exception:
        pass
    db.session.commit()
    flash(f"{shown} is on {item.name}.{extra} Store name stays for the next one.", "success")
    return _after_part_change(item, row.system if row else "", part_id=row.id if row else None)


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
    from datetime import date as _date

    if not getattr(row, "removed_on", None):
        row.removed_on = _date.today()
    try:
        from app.utils.activity import record

        record(
            action="part.off",
            summary=f"{current_user.name or current_user.username} took {row.name} off {item.name}",
            target_table="vehicle_parts",
            target_id=row.id,
            item_id=item.id,
            old_json={"status": "installed", "is_current": True, "name": row.name, "system": row.system},
            new_json={"status": "retired"},
        )
    except Exception:
        pass
    db.session.commit()
    flash(f"{row.name} is off {item.name}. A parent can put it back on Happened.", "info")
    return _after_part_change(item, row.system)


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
    if "model" in request.form:
        row.model = (request.form.get("model") or "").strip()[:120] or None
    if "serial_number" in request.form or "serial" in request.form:
        row.serial_number = (request.form.get("serial_number") or request.form.get("serial") or "").strip()[:120] or None
    if "asset_id" in request.form:
        row.asset_id = (request.form.get("asset_id") or "").strip()[:80] or None
    row.notes = (request.form.get("part_notes") or request.form.get("notes") or "").strip() or None
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
    return _after_part_change(item, row.system, part_id=row.id)


@items_bp.route("/<int:item_id>/delete", methods=["POST"])
@login_required
@require_perm("edit_meta")
def delete_item(item_id):
    from datetime import datetime as _dt
    from app.utils.activity import record
    from sqlalchemy.orm.attributes import flag_modified

    item = _item_or_404(item_id)
    extra = dict(item.extra_data) if isinstance(item.extra_data, dict) else {}
    if item.barcode:
        extra["removed_barcode"] = item.barcode
        item.barcode = None
        item.extra_data = extra
        flag_modified(item, "extra_data")
    item.removed_at = _dt.utcnow()
    record(
        action="item.remove",
        summary=f"{current_user.name or current_user.username} removed {item.name}",
        target_table="items",
        target_id=item.id,
        item_id=item.id,
        old_json={"name": item.name, "item_type": item.item_type},
        reversible=True,
    )
    db.session.commit()
    flash(f"{item.name} is out of the house. A parent can put it back on Happened.", "info")
    return redirect(stay_path(item))
