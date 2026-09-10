from flask import Blueprint, redirect, url_for, abort
from flask_login import login_required, current_user

from app.builddb.builddb import db
from app.builddb.table_households import Household
from app.utils.household import household_id
from app.utils.house_systems import ensure_house_item
from app.utils.permissions import can

house_bp = Blueprint("house", __name__, url_prefix="/house")


@house_bp.route("/")
@login_required
def index():
    hid = household_id()
    household = Household.query.get(hid)
    item, created = ensure_house_item(hid, current_user.id, name=household.name if household else "The house")
    if created:
        db.session.commit()
    return redirect(url_for("items.detail", item_id=item.id, tab="systems"))


@house_bp.route("/open")
@login_required
def open_house():
    if not (can("view") or can("scan")):
        abort(403)
    return redirect(url_for("house.index"))
