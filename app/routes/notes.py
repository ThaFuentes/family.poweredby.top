from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from sqlalchemy import or_

from app.builddb.builddb import db
from app.builddb.table_notes import Note, VISIBILITY
from app.builddb.table_items import Item
from app.builddb.table_users import User
from app.utils.household import household_id, scoped

notes_bp = Blueprint("notes", __name__, url_prefix="/notes")


def _visible(hid, user_id, item_id=None):
    q = Note.query.filter_by(household_id=hid).filter(
        or_(Note.visibility == "household", Note.user_id == user_id)
    )
    if item_id:
        q = q.filter_by(item_id=item_id)
    return q.order_by(Note.updated_at.desc())


def _can_edit(note) -> bool:
    if note.user_id == current_user.id:
        return True
    return bool(getattr(current_user, "is_admin", False))


def _pin_items(hid):
    return (
        Item.query.filter_by(household_id=hid)
        .order_by(Item.item_type.asc(), Item.name.asc())
        .all()
    )


def _authors(hid):
    return {u.id: u for u in User.query.filter_by(household_id=hid).all()}


@notes_bp.route("/")
@login_required
def index():
    hid = household_id()
    uid = current_user.id
    scope = (request.args.get("scope") or "all").strip().lower()
    q = _visible(hid, uid)
    if scope == "mine":
        q = q.filter_by(user_id=uid)
    elif scope == "household":
        q = q.filter_by(visibility="household")
    elif scope == "pinned":
        q = q.filter(Note.item_id.isnot(None))
    elif scope == "projects":
        q = q.filter(Note.item_id.is_(None))
    rows = q.all()
    return render_template(
        "notes.html",
        rows=rows,
        scope=scope,
        items=_pin_items(hid),
        authors=_authors(hid),
        pin_item_id=request.args.get("item_id") or "",
    )


@notes_bp.route("/add", methods=["POST"])
@login_required
def add():
    hid = household_id()
    title = (request.form.get("title") or "").strip()
    body = (request.form.get("body") or "").strip() or None
    vis = (request.form.get("visibility") or "personal").strip().lower()
    if vis not in VISIBILITY:
        vis = "personal"
    raw_item = (request.form.get("item_id") or "").strip()
    item_id = None
    if raw_item.isdigit():
        item = scoped(Item).filter_by(id=int(raw_item)).first()
        item_id = item.id if item else None
    if not title:
        flash("Give the note a name.", "danger")
        return redirect(request.referrer or url_for("notes.index"))
    db.session.add(
        Note(
            household_id=hid,
            user_id=current_user.id,
            item_id=item_id,
            visibility=vis,
            title=title[:500],
            body=body,
        )
    )
    db.session.commit()
    flash("Note saved.", "success")
    if item_id and request.form.get("from_item"):
        return redirect(url_for("items.detail", item_id=item_id, tab="notes"))
    return redirect(url_for("notes.index"))


@notes_bp.route("/<int:note_id>/edit", methods=["POST"])
@login_required
def edit(note_id):
    note = scoped(Note).filter_by(id=note_id).first_or_404()
    if not _can_edit(note):
        abort(403)
    title = (request.form.get("title") or "").strip()
    if not title:
        flash("Give the note a name.", "danger")
        return redirect(request.referrer or url_for("notes.index"))
    vis = (request.form.get("visibility") or note.visibility).strip().lower()
    if vis not in VISIBILITY:
        vis = note.visibility
    raw_item = (request.form.get("item_id") or "").strip()
    item_id = None
    if raw_item.isdigit():
        item = scoped(Item).filter_by(id=int(raw_item)).first()
        item_id = item.id if item else None
    note.title = title[:500]
    note.body = (request.form.get("body") or "").strip() or None
    note.visibility = vis
    note.item_id = item_id
    note.updated_at = datetime.utcnow()
    db.session.commit()
    flash("Note updated.", "success")
    if item_id and request.form.get("from_item"):
        return redirect(url_for("items.detail", item_id=item_id, tab="notes"))
    return redirect(url_for("notes.index"))


@notes_bp.route("/<int:note_id>/delete", methods=["POST"])
@login_required
def delete(note_id):
    note = scoped(Note).filter_by(id=note_id).first_or_404()
    if not _can_edit(note):
        abort(403)
    item_id = note.item_id
    db.session.delete(note)
    db.session.commit()
    flash("Note removed.", "info")
    if item_id and request.form.get("from_item"):
        return redirect(url_for("items.detail", item_id=item_id, tab="notes"))
    return redirect(url_for("notes.index"))
