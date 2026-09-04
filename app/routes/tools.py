from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from app.builddb.builddb import db
from app.builddb.table_items import Item
from app.builddb.table_tools import Tool
from app.utils.household import household_id
from app.utils.permissions import can
from app.utils.qr_labels import item_payload
from app.routes.items import save_item_photo, can_create_type

tools_bp = Blueprint("tools", __name__, url_prefix="/tools")


@tools_bp.route("/")
@login_required
def index():
    hid = household_id()
    items = (
        Item.query.filter_by(household_id=hid, item_type="tool")
        .order_by(Item.name.asc())
        .all()
    )
    return render_template("tools.html", items=items, can_add=can_create_type("tool"))


@tools_bp.route("/add", methods=["POST"])
@login_required
def add():
    if not can_create_type("tool"):
        abort(403)
    hid = household_id()
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Name the tool.", "danger")
        return redirect(url_for("tools.index"))
    item = Item(
        household_id=hid,
        name=name[:200],
        item_type="tool",
        category=(request.form.get("tool_type") or "").strip() or None,
        notes=(request.form.get("notes") or "").strip() or None,
        created_by=current_user.id,
    )
    db.session.add(item)
    db.session.flush()
    barcode = (request.form.get("barcode") or "").strip() or None
    item.barcode = barcode or item_payload(hid, item.id)
    hours = request.form.get("maintenance_interval_hours") or ""
    t = Tool(
        item_id=item.id,
        household_id=hid,
        type=(request.form.get("tool_type") or "").strip() or None,
        power_source=(request.form.get("power_source") or "").strip() or None,
        oil_type=(request.form.get("oil_type") or "").strip() or None,
        fuel_type=(request.form.get("fuel_type") or "").strip() or None,
        usage_notes=(request.form.get("usage_notes") or "").strip() or None,
        maintenance_interval_hours=int(hours) if str(hours).isdigit() else None,
    )
    db.session.add(t)
    photo = request.files.get("photo")
    if photo and photo.filename:
        save_item_photo(item, photo, request.form.get("caption"), current_user.id)
    db.session.commit()
    flash(f"{item.name} saved. QR is optional — print one later if you want.", "success")
    return redirect(url_for("items.detail", item_id=item.id))
