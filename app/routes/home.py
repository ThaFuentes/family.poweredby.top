from flask import Blueprint, render_template, redirect, url_for
from flask_login import login_required, current_user

from app.builddb.table_grocery_list import GroceryListEntry
from app.builddb.table_reminders import Reminder
from app.builddb.table_items import Item
from app.utils.household import household_id, scoped

home_bp = Blueprint("home", __name__)


@home_bp.route("/")
def home():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    hid = household_id()
    grocery_open = scoped(GroceryListEntry).filter_by(status="open").count()
    reminders_open = scoped(Reminder).filter_by(status="open").count()
    counts = {
        "groceries": scoped(Item).filter_by(item_type="grocery").count(),
        "tools": scoped(Item).filter_by(item_type="tool").count(),
        "vehicles": scoped(Item).filter_by(item_type="vehicle").count(),
        "list": grocery_open,
        "reminders": reminders_open,
    }
    return render_template("home.html", counts=counts)
