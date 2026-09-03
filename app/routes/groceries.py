from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app.builddb.builddb import db
from app.builddb.table_items import Item
from app.builddb.table_grocery_list import GroceryListEntry
from app.utils.household import household_id, scoped
from app.utils.permissions import require_perm

groceries_bp = Blueprint("groceries", __name__, url_prefix="/groceries")


@groceries_bp.route("/")
@login_required
def index():
    hid = household_id()
    q = (
        Item.query.filter_by(household_id=hid, item_type="grocery")
        .order_by(Item.name.asc())
        .all()
    )
    return render_template("groceries.html", items=q)


@groceries_bp.route("/list")
@login_required
def grocery_list():
    rows = (
        scoped(GroceryListEntry)
        .filter_by(status="open")
        .order_by(GroceryListEntry.created_at.desc())
        .all()
    )
    return render_template("grocery_list.html", rows=rows)


@groceries_bp.route("/list/add", methods=["POST"])
@login_required
@require_perm("edit_grocery")
def list_add():
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Name required.", "danger")
        return redirect(url_for("groceries.grocery_list"))
    db.session.add(
        GroceryListEntry(
            household_id=household_id(),
            name=name,
            status="open",
            added_reason="manual",
            created_by=current_user.id,
        )
    )
    db.session.commit()
    return redirect(url_for("groceries.grocery_list"))


@groceries_bp.route("/list/<int:entry_id>/done", methods=["POST"])
@login_required
@require_perm("edit_grocery")
def list_done(entry_id):
    row = scoped(GroceryListEntry).filter_by(id=entry_id).first_or_404()
    row.status = "done"
    row.completed_at = datetime.utcnow()
    db.session.commit()
    return redirect(url_for("groceries.grocery_list"))


@groceries_bp.route("/list/<int:entry_id>/remove", methods=["POST"])
@login_required
@require_perm("edit_grocery")
def list_remove(entry_id):
    row = scoped(GroceryListEntry).filter_by(id=entry_id).first_or_404()
    db.session.delete(row)
    db.session.commit()
    return redirect(url_for("groceries.grocery_list"))
