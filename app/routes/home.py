from flask import Blueprint, render_template, redirect, url_for
from flask_login import current_user
from sqlalchemy import or_

from app.builddb.table_grocery_list import GroceryListEntry
from app.builddb.table_items import Item
from app.builddb.table_notes import Note
from app.builddb.table_reminders import Reminder
from app.utils.household import household_id, scoped
from app.utils.needs import household_needs
from app.utils.permissions import role_of

home_bp = Blueprint("home", __name__)


@home_bp.route("/")
def home():
    if not current_user.is_authenticated:
        return render_template("landing.html")
    hid = household_id()
    try:
        from app.utils.notify import flush_due_emails

        flush_due_emails(hid)
    except Exception:
        pass
    is_child = role_of() == "child"
    needs = household_needs(hid, is_child=is_child)
    grocery_open = scoped(GroceryListEntry).filter_by(status="open").count()
    reminders_open = scoped(Reminder).filter_by(status="open").count()
    notes_open = scoped(Note).filter(
        or_(Note.visibility == "household", Note.user_id == current_user.id)
    ).count()
    house = (
        Item.query.filter_by(household_id=hid, item_type="house")
        .order_by(Item.id.asc())
        .first()
    )
    counts = {
        "groceries": scoped(Item).filter_by(item_type="grocery").count(),
        "tools": scoped(Item).filter_by(item_type="tool").count(),
        "vehicles": scoped(Item).filter_by(item_type="vehicle").count(),
        "list": grocery_open,
        "reminders": reminders_open,
        "out": needs["out"],
        "low": needs["low"],
        "want": needs["want"],
        "notes": notes_open,
    }
    tmpl = "home_kid.html" if is_child else "home.html"
    return render_template(
        tmpl,
        counts=counts,
        needs=needs,
        house=house,
        is_child=is_child,
    )
