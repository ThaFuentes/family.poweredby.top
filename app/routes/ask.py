from flask import Blueprint, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.builddb.table_households import Household
from app.utils.ask import ask_chat_allowed, ask_identity, ask_ready, clear_history, history_payload, run_ask
from app.utils.ask_photo import image_from_payload
from app.utils.ask_rooms import help_text, normalize_room, room_from_path, room_meta, rooms_public
from app.utils.household import household_id

ask_bp = Blueprint("ask", __name__, url_prefix="/ask")
RESERVED = frozenset({"message", "history", "clear", "help", "mine"})


def _household():
    return Household.query.get(household_id())


def _room_arg(payload=None) -> str:
    payload = payload if isinstance(payload, dict) else {}
    raw = payload.get("room") or request.args.get("room") or request.form.get("room") or ""
    if raw:
        return normalize_room(raw)
    return room_from_path(request.path)


def _desk(room_key: str):
    key = normalize_room(room_key)
    h = _household()
    if not ask_chat_allowed(h, current_user):
        return redirect(url_for("home.home"))
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
    h = _household()
    if not ask_chat_allowed(h, current_user):
        return jsonify({"ok": False, "error": "Ask is off for this household."}), 403
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
    if not ask_chat_allowed(_household(), current_user):
        return jsonify({"ok": False, "turns": []}), 403
    return jsonify(history_payload(_room_arg()))


@ask_bp.route("/clear", methods=["POST"])
@login_required
def clear():
    payload = request.get_json(silent=True) or {}
    clear_history(_room_arg(payload))
    return jsonify({"ok": True})


@ask_bp.route("/mine", methods=["POST"])
@login_required
def mine():
    """This person's chat name and instructions. House rules stay on Household."""
    h = _household()
    if not ask_chat_allowed(h, current_user):
        return jsonify({"ok": False, "error": "Ask is off for this household."}), 403
    if not ask_ready(h, current_user):
        return jsonify({"ok": False, "error": "Turn on a household AI key before naming the chat."}), 403
    from app.utils.household_ai import set_user_agent

    payload = request.get_json(silent=True) or {}
    fields = {}
    if "name" in payload or "name" in request.form:
        fields["name"] = payload["name"] if "name" in payload else request.form.get("name")
    if "instructions" in payload or "instructions" in request.form:
        raw_notes = payload["instructions"] if "instructions" in payload else request.form.get("instructions")
        fields["instructions"] = raw_notes
    if fields:
        set_user_agent(current_user, **fields)
    identity = ask_identity(h, current_user)
    return jsonify(
        {
            "ok": True,
            "name": identity.get("name") or "Ask",
            "user_name": identity.get("user_name") or "",
            "instructions": identity.get("user_instructions") or "",
            "house_rules": identity.get("persona") or "",
        }
    )


@ask_bp.route("/help", methods=["GET"])
@login_required
def help_page():
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
