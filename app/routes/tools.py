from flask import Blueprint, render_template
from flask_login import login_required

from app.builddb.table_items import Item
from app.utils.household import household_id

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
    return render_template("tools.html", items=items)
