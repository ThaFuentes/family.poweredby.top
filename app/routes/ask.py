from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app.builddb.table_households import Household
from app.utils.ask import ask_ready, clear_history, run_ask
from app.utils.household import household_id
from app.utils.permissions import role_of

ask_bp = Blueprint("ask", __name__, url_prefix="/ask")


def _household():
    return Household.query.get(household_id())


@ask_bp.route("/message", methods=["POST"])
@login_required
def message():
    if role_of() == "child":
        return jsonify({"ok": False, "error": "Ask is for grown-ups."}), 403
    h = _household()
    if not ask_ready(h, current_user):
        return jsonify({"ok": False, "error": "Ask is off. Add an AI key in Household."}), 403
    payload = request.get_json(silent=True) or {}
    text = payload.get("message") or request.form.get("message") or ""
    result = run_ask(text, household=h)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@ask_bp.route("/clear", methods=["POST"])
@login_required
def clear():
    if role_of() == "child":
        return jsonify({"ok": False}), 403
    clear_history()
    return jsonify({"ok": True})
