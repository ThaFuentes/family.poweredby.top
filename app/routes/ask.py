from flask import Blueprint, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.builddb.table_households import Household
from app.utils.ask import ask_ready, clear_history, history_payload, run_ask
from app.utils.ask_photo import image_from_payload
from app.utils.ask_rooms import help_text, normalize_room, room_from_path, room_meta, rooms_public
from app.utils.household import household_id
from app.utils.permissions import role_of

ask_bp = Blueprint("ask", __name__, url_prefix="/ask")
RESERVED = frozenset({"message", "history", "clear", "help"})


def _household():
    return Household.query.get(household_id())


def _room_arg(payload=None) -> str:
    payload = payload if isinstance(payload, dict) else {}
    raw = payload.get("room") or request.args.get("room") or request.form.get("room") or ""
    if raw:
        return normalize_room(raw)
    return room_from_path(request.path)


def _desk(room_key: str):
    if role_of() == "child":
        return redirect(url_for("home.home"))
    key = normalize_room(room_key)
    h = _household()
    if not ask_ready(h, current_user):
        return render_template(
            "ask_help.html",
            rooms=rooms_public(),
            help_body=help_text(key),
            need_key=True,
        )
    meta = room_meta(key)
    return render_template(
        "ask.html",
        ask_room=key,
        ask_mode="desk",
        room=meta,
        rooms=rooms_public(),
        help_href=url_for("ask.help_page"),
    )


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
    image_bytes, image_mime, image_err = image_from_payload(payload, request.files.get("image"))
    if image_err:
        return jsonify({"ok": False, "error": image_err}), 400
    result = run_ask(
        text,
        household=h,
        image_bytes=image_bytes,
        image_mime=image_mime,
        room=_room_arg(payload),
    )
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@ask_bp.route("/history", methods=["GET"])
@login_required
def history():
    if role_of() == "child":
        return jsonify({"ok": False, "turns": []}), 403
    if not ask_ready(_household(), current_user):
        return jsonify({"ok": False, "turns": []}), 403
    return jsonify(history_payload(_room_arg()))


@ask_bp.route("/clear", methods=["POST"])
@login_required
def clear():
    if role_of() == "child":
        return jsonify({"ok": False}), 403
    payload = request.get_json(silent=True) or {}
    clear_history(_room_arg(payload))
    return jsonify({"ok": True})


@ask_bp.route("/help", methods=["GET"])
@login_required
def help_page():
    if role_of() == "child":
        return redirect(url_for("home.home"))
    return render_template(
        "ask_help.html",
        rooms=rooms_public(),
        help_body=help_text("house"),
        need_key=not ask_ready(_household(), current_user),
    )


@ask_bp.route("/", methods=["GET"])
@login_required
def index():
    return _desk("house")


@ask_bp.route("/<room>", methods=["GET"])
@login_required
def room(room):
    if (room or "").strip().lower() in RESERVED:
        return redirect(url_for("ask.index"))
    return _desk(room)
