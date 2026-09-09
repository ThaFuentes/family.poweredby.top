from flask import Blueprint, render_template, redirect, url_for
from flask_login import current_user
from sqlalchemy import or_

from app.builddb.table_grocery_list import GroceryListEntry
from app.builddb.table_grocery_items import GroceryItem
from app.builddb.table_reminders import Reminder
from app.builddb.table_items import Item
from app.builddb.table_notes import Note
from app.utils.household import scoped

home_bp = Blueprint("home", __name__)


@home_bp.route("/")
def home():
    if not current_user.is_authenticated:
        return render_template("landing.html")
    try:
        from app.utils.notify import flush_due_emails
        from app.utils.household import household_id as _hid

        flush_due_emails(_hid())
    except Exception:
        pass
    grocery_open = scoped(GroceryListEntry).filter_by(status="open").count()
    reminders_open = scoped(Reminder).filter_by(status="open").count()
    notes_open = scoped(Note).filter(
        or_(Note.visibility == "household", Note.user_id == current_user.id)
    ).count()
    pantry = scoped(GroceryItem)
    had_filter = or_(
        GroceryItem.last_restocked_at.isnot(None),
        GroceryItem.last_consumed_at.isnot(None),
        GroceryItem.consume_count > 0,
    )
    out = pantry.filter(GroceryItem.is_in_stock.is_(False), had_filter).count()
    want = pantry.filter(
        GroceryItem.is_in_stock.is_(False),
        GroceryItem.last_restocked_at.is_(None),
        GroceryItem.last_consumed_at.is_(None),
        GroceryItem.consume_count == 0,
    ).count()
    low = pantry.filter_by(is_in_stock=True, needs_restock=True).count()
    counts = {
        "groceries": scoped(Item).filter_by(item_type="grocery").count(),
        "tools": scoped(Item).filter_by(item_type="tool").count(),
        "vehicles": scoped(Item).filter_by(item_type="vehicle").count(),
        "list": grocery_open,
        "reminders": reminders_open,
        "out": out,
        "low": low,
        "want": want,
        "notes": notes_open,
    }
    return render_template("home.html", counts=counts)
