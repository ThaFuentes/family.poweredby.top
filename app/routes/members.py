from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from app.builddb.builddb import db
from app.builddb.table_users import User, ROLES
from app.builddb.table_invites import Invite
from app.builddb.table_households import Household
from app.utils.household import household_id, scoped
from app.utils.permissions import require_perm

members_bp = Blueprint("members", __name__, url_prefix="/members")


@members_bp.route("/")
@login_required
def index():
    if current_user.role == "child":
        abort(403)
    hid = household_id()
    members = User.query.filter_by(household_id=hid).order_by(User.name.asc()).all()
    invites = (
        Invite.query.filter_by(household_id=hid)
        .filter(Invite.used_at.is_(None))
        .order_by(Invite.created_at.desc())
        .all()
    )
    household = Household.query.get(hid)
    from app.utils.calendar import household_reminders_via
    from app.utils.ai import public_ai_config
    from app.builddb.table_service_passes import ServicePass
    from app.builddb.table_trusted_emails import TrustedEmail

    service_keys = (
        ServicePass.query.filter_by(household_id=hid)
        .order_by(ServicePass.created_at.desc())
        .limit(40)
        .all()
    )
    trusted = (
        TrustedEmail.query.filter_by(household_id=hid)
        .order_by(TrustedEmail.created_at.desc())
        .all()
    )
    from app.utils.places import list_places
    from app.utils.keys_ui import pop_issued_key
    from app.utils.household_delete import confirm_phrase

    return render_template(
        "members.html",
        issued_key=pop_issued_key(),
        delete_confirm=confirm_phrase(household) if household else "",
        members=members,
        invites=invites,
        household=household,
        roles=ROLES,
        reminders_via=household_reminders_via(household),
        is_leader=bool(current_user.is_leader),
        ai=public_ai_config(household, household_only=True),
        service_keys=service_keys,
        trusted=trusted,
        can_mint_service=current_user.role != "child",
        places_text="\n".join(list_places(household)),
    )


@members_bp.route("/invite", methods=["POST"])
@login_required
@require_perm("members")
def invite():
    role = (request.form.get("role") or "member").strip().lower()
    if role not in ROLES:
        role = "member"
    code = Invite.new_code()
    db.session.add(
        Invite(
            household_id=household_id(),
            code=code,
            role=role,
            created_by=current_user.id,
            expires_at=datetime.utcnow() + timedelta(days=14),
        )
    )
    db.session.commit()
    from app.utils.keys_ui import stash_issued_key

    stash_issued_key(
        code,
        "Family key",
        f"Joins this household as {role}. Not a Service key.",
    )
    flash("Family key ready — copy it from the window.", "success")
    return redirect(url_for("members.index"))


@members_bp.route("/service-key", methods=["POST"])
@login_required
def mint_service_key():
    if current_user.role == "child":
        flash("Kids cannot mint Service keys.", "warning")
        return redirect(url_for("home.home"))
    from app.utils.access import mint_service_pass

    row = mint_service_pass(
        created_by=current_user.id,
        household_id=household_id(),
        label=(request.form.get("label") or "").strip(),
        max_uses=request.form.get("max_uses") or 1,
        days=request.form.get("days") or 14,
    )
    from app.utils.keys_ui import stash_issued_key

    stash_issued_key(
        row.code,
        "Service key",
        "Gets a friend onto Family OS. Does not put them in this household.",
    )
    flash("Service key ready — copy it from the window.", "success")
    return redirect(url_for("members.index"))


@members_bp.route("/service-key/<int:kid>/revoke", methods=["POST"])
@login_required
def revoke_service_key(kid):
    if current_user.role == "child":
        abort(403)
    from app.builddb.table_service_passes import ServicePass
    from app.utils.access import revoke_service_pass

    row = ServicePass.query.filter_by(id=kid, household_id=household_id()).first_or_404()
    revoke_service_pass(row)
    flash(f"{row.code} revoked.", "info")
    return redirect(url_for("members.index"))


@members_bp.route("/trusted", methods=["POST"])
@login_required
@require_perm("members")
def add_trusted():
    from app.utils.access import add_trusted_email

    ok, msg, _row = add_trusted_email(
        email=request.form.get("email") or "",
        added_by=current_user.id,
        household_id=household_id(),
        note=request.form.get("note") or "",
    )
    flash(msg, "success" if ok else "danger")
    return redirect(url_for("members.index"))


@members_bp.route("/trusted/<int:tid>/remove", methods=["POST"])
@login_required
@require_perm("members")
def remove_trusted(tid):
    from app.builddb.table_trusted_emails import TrustedEmail

    row = TrustedEmail.query.filter_by(id=tid, household_id=household_id()).first_or_404()
    addr = row.email
    db.session.delete(row)
    db.session.commit()
    flash(f"{addr} is no longer on the trusted list.", "info")
    return redirect(url_for("members.index"))


@members_bp.route("/<int:user_id>/role", methods=["POST"])
@login_required
@require_perm("members")
def set_role(user_id):
    hid = household_id()
    user = User.query.filter_by(id=user_id, household_id=hid).first_or_404()
    if user.id == current_user.id:
        flash("You cannot change your own role here.", "warning")
        return redirect(url_for("members.index"))
    role = (request.form.get("role") or "").strip().lower()
    if role not in ROLES:
        flash("Invalid role.", "danger")
        return redirect(url_for("members.index"))
    if role == "child" and user.is_leader:
        from app.utils.leaders import leader_count

        if leader_count(hid) <= 1:
            flash("Promote another leader before making this person a child.", "warning")
            return redirect(url_for("members.index"))
        user.is_leader = False
    user.role = role
    db.session.commit()
    flash(f"{user.name} is now {role}.", "success")
    return redirect(url_for("members.index"))


@members_bp.route("/<int:user_id>/leader", methods=["POST"])
@login_required
@require_perm("leaders")
def set_leader_flag(user_id):
    hid = household_id()
    if not current_user.is_leader:
        flash("Only household leaders can change who the leaders are.", "warning")
        return redirect(url_for("members.index"))
    user = User.query.filter_by(id=user_id, household_id=hid).first_or_404()
    make = (request.form.get("leader") or "").strip() in ("1", "true", "on", "yes")
    from app.utils.leaders import set_leader

    ok, msg = set_leader(user, make)
    flash(msg, "success" if ok else "danger")
    return redirect(url_for("members.index"))


@members_bp.route("/<int:user_id>/reset", methods=["POST"])
@login_required
@require_perm("leaders")
def send_member_reset(user_id):
    hid = household_id()
    if not current_user.is_leader:
        flash("Only household leaders can send a reset for someone here.", "warning")
        return redirect(url_for("members.index"))
    user = User.query.filter_by(id=user_id, household_id=hid, is_active=True).first_or_404()
    from app.utils.passwords import issue_reset, send_reset_email

    token = issue_reset(user, requested_by=current_user.id)
    if not token:
        flash(f"{user.name} needs an email on this household first.", "warning")
        return redirect(url_for("members.index"))
    ok, msg = send_reset_email(user, token)
    flash(msg if not ok else f"Reset link sent to {user.email}.", "success" if ok else "danger")
    return redirect(url_for("members.index"))


@members_bp.route("/reminders-via", methods=["POST"])
@login_required
@require_perm("leaders")
def set_reminders_via():
    from app.utils.calendar import set_household_reminders_via

    h = Household.query.get(household_id())
    set_household_reminders_via(h, request.form.get("reminders_via") or "both")
    flash("Reminder delivery updated for this household.", "success")
    nxt = (request.form.get("next") or "").strip()
    if nxt == "reminders":
        return redirect(url_for("reminders.index"))
    return redirect(url_for("members.index"))


@members_bp.route("/<int:user_id>/email", methods=["POST"])
@login_required
@require_perm("members")
def set_email(user_id):
    hid = household_id()
    user = User.query.filter_by(id=user_id, household_id=hid).first_or_404()
    email = (request.form.get("email") or "").strip().lower() or None
    if email:
        taken = User.query.filter(User.email == email, User.id != user.id).first()
        if taken:
            flash("That email is already used.", "danger")
            return redirect(url_for("members.index"))
    user.email = email
    db.session.commit()
    flash("Email updated.", "success")
    return redirect(url_for("members.index"))


@members_bp.route("/ai", methods=["POST"])
@login_required
@require_perm("settings")
def save_ai():
    from app.utils.ai import normalize_provider
    from app.utils.household_ai import save_household_ai

    h = Household.query.get(household_id())
    save_household_ai(
        h,
        provider=normalize_provider(request.form.get("ai_provider")),
        model=(request.form.get("ai_model") or "").strip(),
        api_key=(request.form.get("ai_api_key") or "").strip(),
        base_url=(request.form.get("ai_base_url") or "").strip(),
        enabled=(request.form.get("ai_enabled") or "1") != "0",
        clear_key=(request.form.get("ai_clear_key") or "") == "1",
    )
    flash("Household AI key saved. It stays on this household — never in the browser.", "success")
    return redirect(url_for("members.index"))


@members_bp.route("/ai/test", methods=["POST"])
@login_required
@require_perm("settings")
def test_ai():
    from app.utils.ai import ping_ai

    h = Household.query.get(household_id())
    ok, msg = ping_ai(h, household_only=True)
    flash(msg, "success" if ok else "danger")
    return redirect(url_for("members.index"))


@members_bp.route("/rename", methods=["POST"])
@login_required
@require_perm("settings")
def rename_household():
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Household name required.", "danger")
        return redirect(url_for("members.index"))
    h = Household.query.get(household_id())
    h.name = name
    db.session.commit()
    flash("Household renamed.", "success")
    return redirect(url_for("members.index"))


@members_bp.route("/handle", methods=["POST"])
@login_required
@require_perm("settings")
def save_handle():
    from app.utils.identity import valid_handle, norm_handle

    h = Household.query.get(household_id())
    raw = norm_handle(request.form.get("handle") or "")
    if not valid_handle(raw):
        flash("Handle: start with a letter, letters and numbers only. This is how you sign in.", "danger")
        return redirect(url_for("members.index"))
    taken = Household.query.filter(Household.handle == raw, Household.id != h.id).first()
    if taken:
        flash("That household handle is taken. Try another.", "danger")
        return redirect(url_for("members.index"))
    h.handle = raw
    db.session.commit()
    flash(f"Household handle is {raw}. Sign in with that plus your username.", "success")
    return redirect(url_for("members.index"))


@members_bp.route("/delete", methods=["POST"])
@login_required
@require_perm("settings")
def delete_household():
    from flask_login import logout_user

    from app.utils.household_delete import confirm_matches, confirm_phrase, delete_household as wipe

    h = Household.query.get(household_id())
    typed = request.form.get("confirm") or ""
    if not confirm_matches(h, typed):
        flash(f'Type "{confirm_phrase(h)}" to delete this household.', "danger")
        return redirect(url_for("members.index"))
    name = wipe(h)
    logout_user()
    flash(f"{name} is gone. That cannot be undone.", "info")
    return redirect(url_for("home.home"))


@members_bp.route("/<int:user_id>/username", methods=["POST"])
@login_required
@require_perm("members")
def set_username(user_id):
    from app.utils.identity import norm_username, username_taken, valid_username

    hid = household_id()
    user = User.query.filter_by(id=user_id, household_id=hid).first_or_404()
    raw = norm_username(request.form.get("username") or "")
    if not valid_username(raw):
        flash("Username: start with a letter, then letters, numbers, underscore.", "danger")
        return redirect(url_for("members.index"))
    if username_taken(hid, raw, exclude_id=user.id):
        flash("Someone in this household already uses that username.", "danger")
        return redirect(url_for("members.index"))
    user.username = raw
    db.session.commit()
    flash(f"{user.name} signs in as {raw}.", "success")
    return redirect(url_for("members.index"))


@members_bp.route("/places", methods=["POST"])
@login_required
@require_perm("settings")
def save_places():
    from app.utils.places import save_places as _save

    h = Household.query.get(household_id())
    names = _save(h, request.form.get("places") or "")
    db.session.commit()
    flash(f"Saved {len(names)} places.", "success")
    return redirect(url_for("members.index"))
