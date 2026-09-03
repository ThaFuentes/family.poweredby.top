from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app.builddb.builddb import db
from app.builddb.table_reminders import Reminder
from app.builddb.table_items import Item
from app.utils.household import household_id, scoped
from app.utils.permissions import require_perm

reminders_bp = Blueprint("reminders", __name__, url_prefix="/reminders")


@reminders_bp.route("/")
@login_required
def index():
    rows = scoped(Reminder).order_by(Reminder.due_at.asc()).all()
    items = scoped(Item).order_by(Item.name.asc()).all()
    return render_template("reminders.html", rows=rows, items=items)


@reminders_bp.route("/add", methods=["POST"])
@login_required
@require_perm("maintain")
def add():
    title = (request.form.get("title") or "").strip()
    rtype = (request.form.get("type") or "custom").strip()
    due = (request.form.get("due_at") or "").strip()
    linked = request.form.get("linked_item_id") or None
    recurrence = (request.form.get("recurrence") or "").strip() or None
    if not title:
        flash("Title required.", "danger")
        return redirect(url_for("reminders.index"))
    due_at = None
    if due:
        try:
            due_at = datetime.fromisoformat(due)
        except ValueError:
            due_at = None
    linked_id = int(linked) if linked else None
    db.session.add(
        Reminder(
            household_id=household_id(),
            title=title,
            type=rtype,
            due_at=due_at,
            linked_item_id=linked_id,
            recurrence=recurrence,
            status="open",
            created_by=current_user.id,
        )
    )
    db.session.commit()
    return redirect(url_for("reminders.index"))


@reminders_bp.route("/<int:rid>/done", methods=["POST"])
@login_required
@require_perm("maintain")
def done(rid):
    row = scoped(Reminder).filter_by(id=rid).first_or_404()
    row.status = "done"
    db.session.commit()
    return redirect(url_for("reminders.index"))
