from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from flask_login import login_required, current_user

from app.utils.household import household_id
from app.utils.permissions import can
from app.utils.scan import process_scan

scan_bp = Blueprint("scan", __name__, url_prefix="/scan")


@scan_bp.route("/")
@login_required
def scan_page():
    if not can("scan"):
        return redirect(url_for("home.home"))
    default_action = (request.args.get("action") or "auto").strip().lower()
    if default_action not in ("auto", "consume", "restock"):
        default_action = "auto"
    return render_template("scan.html", default_action=default_action)


@scan_bp.route("/apply", methods=["POST"])
@login_required
def scan_apply():
    if not can("scan"):
        return jsonify({"error": "scan not allowed"}), 403
    data = request.get_json(silent=True) or request.form
    barcode = (data.get("barcode") or "").strip()
    action = (data.get("action") or "auto").strip().lower()
    amount = data.get("amount") or 1
    if not barcode:
        return jsonify({"error": "barcode required"}), 400
    result = process_scan(household_id(), current_user.id, barcode, action, amount)
    return jsonify(result)
