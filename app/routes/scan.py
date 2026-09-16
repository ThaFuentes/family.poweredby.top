from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from flask_login import login_required, current_user

from app.builddb.builddb import db
from app.utils.household import household_id
from app.utils.permissions import can
from app.utils.scan import process_scan

scan_bp = Blueprint("scan", __name__, url_prefix="/scan")


@scan_bp.route("/")
@login_required
def scan_page():
    if not can("scan"):
        return redirect(url_for("home.home"))
    return render_template(
        "scan.html",
        can_create=can("edit_grocery") or can("edit_meta") or can("maintain"),
        scan_kind="any",
    )


@scan_bp.route("/apply", methods=["POST"])
@login_required
def scan_apply():
    if not can("scan"):
        return jsonify({"error": "scan not allowed"}), 403
    data = request.get_json(silent=True) or request.form
    barcode = (data.get("barcode") or "").strip()
    action = (data.get("action") or "check").strip().lower()
    amount = data.get("amount") or 1
    location = (data.get("location") or "").strip() or None
    skip_place = str(data.get("skip_place") or "").strip().lower() in ("1", "true", "yes")
    skip_host = str(data.get("skip_host") or "").strip().lower() in ("1", "true", "yes")
    force_new = str(data.get("create_new") or data.get("force_new") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    host_item_id = data.get("host_item_id")
    fields = data.get("fields")
    if isinstance(fields, str):
        fields = [f.strip() for f in fields.split(",") if f.strip()]
    if not barcode:
        return jsonify({"error": "barcode required"}), 400
    try:
        result = process_scan(
            household_id(),
            current_user.id,
            barcode,
            action,
            amount,
            location=location,
            skip_place=skip_place,
            host_item_id=host_item_id,
            fields=fields,
            skip_host=skip_host,
            force_new=force_new,
        )
    except Exception:
        db.session.rollback()
        return jsonify({"error": "Could not update the household. Try again."}), 500
    if result.get("create"):
        result["can_create"] = can("edit_grocery") or can("edit_meta") or can("maintain")
    return jsonify(result)


@scan_bp.route("/undo", methods=["POST"])
@login_required
def scan_undo():
    if not can("scan"):
        return jsonify({"error": "scan not allowed"}), 403
    data = request.get_json(silent=True) or request.form
    try:
        aid = int(data.get("undo_id") or 0)
    except (TypeError, ValueError):
        aid = 0
    if not aid:
        return jsonify({"ok": False, "error": "Nothing to undo."}), 400
    from app.builddb.table_household_activity import HouseholdActivity
    from app.utils.activity import reverse_row

    row = HouseholdActivity.query.filter_by(id=aid, household_id=household_id()).first()
    if row is None:
        return jsonify({"ok": False, "error": "Already gone."}), 404
    ok, msg = reverse_row(row, by_id=current_user.id)
    return jsonify({"ok": ok, "message": msg})
