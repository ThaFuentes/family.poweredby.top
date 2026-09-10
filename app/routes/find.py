from flask import Blueprint, render_template, request
from flask_login import login_required, current_user

from app.utils.household import household_id
from app.utils.search import search_household

find_bp = Blueprint("find", __name__, url_prefix="/find")


@find_bp.route("/")
@login_required
def index():
    q = (request.args.get("q") or "").strip()
    hits = search_household(household_id(), q, user_id=current_user.id)
    return render_template("find.html", hits=hits, q=q)
