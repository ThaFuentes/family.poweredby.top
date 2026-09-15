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

SHEETS = (
    "people",
    "add",
    "house",
    "keys",
    "mail",
    "lock",
    "ai",
    "trusted",
    "remind",
    "danger",
)


def _after(panel=None):
    nxt = (request.form.get("next") or request.args.get("next") or "").strip()
    p = (panel or request.form.get("panel") or request.args.get("panel") or "").strip()
    if nxt == "sheet" and p in SHEETS:
        return redirect(url_for("members.sheet", panel=p))
    return _after()


def _page_ctx():
    hid = household_id()
    members = User.query.filter_by(household_id=hid).order_by(User.name.asc()).all()
    invites = (
        Invite.query.filter_by(household_id=hid)
        .filter(Invite.used_at.is_(None))
        .filter(Invite.revoked_at.is_(None))
        .order_by(Invite.created_at.desc())
        .all()
    )
    household = Household.query.get(hid)
    from app.utils.calendar import household_reminders_via
    from app.utils.ai import public_ai_config
    from app.builddb.table_service_passes import ServicePass
    from app.builddb.table_trusted_emails import TrustedEmail
    from app.utils.places import list_places
    from app.utils.keys_ui import pop_issued_key
    from app.utils.household_delete import confirm_phrase
    from app.utils.household_vault import FORMAT_HINT, vault_enabled, vault_hint, vault_unlocked
    from app.utils.household_mail import public_mail_config

    show_revoked = (request.args.get("revoked") or "").strip() in ("1", "yes", "all")
    service_q = ServicePass.query.filter_by(household_id=hid)
    revoked_count = service_q.filter(ServicePass.revoked_at.isnot(None)).count()
    if show_revoked:
        service_keys = service_q.order_by(ServicePass.created_at.desc()).limit(60).all()
    else:
        service_keys = (
            service_q.filter(ServicePass.revoked_at.is_(None))
            .order_by(ServicePass.created_at.desc())
            .limit(40)
            .all()
        )
    trusted = (
        TrustedEmail.query.filter_by(household_id=hid)
        .order_by(TrustedEmail.created_at.desc())
        .all()
    )
    return {
        "issued_key": pop_issued_key(),
        "delete_confirm": confirm_phrase(household) if household else "",
        "members": members,
        "invites": invites,
        "household": household,
        "roles": ROLES,
        "reminders_via": household_reminders_via(household),
        "is_leader": bool(current_user.is_leader),
        "ai": public_ai_config(household, household_only=True),
        "service_keys": service_keys,
        "show_revoked": show_revoked,
        "revoked_count": revoked_count,
        "trusted": trusted,
        "can_mint_service": current_user.role != "child",
        "places_text": "\n".join(list_places(household)),
        "vault_on": vault_enabled(household),
        "vault_hint": vault_hint(household),
        "vault_unlocked": vault_unlocked(household),
        "vault_format": FORMAT_HINT,
        "mail": public_mail_config(household),
    }


@members_bp.route("/happened")
@login_required
@require_perm("override")
def happened():
    from app.utils.activity import recent

    hid = household_id()
    hours = request.args.get("hours") or "48"
    try:
        hours_n = int(hours)
    except Exception:
        hours_n = 48
    if hours_n <= 0:
        hours_n = None
    rows = recent(hid, limit=80, hours=hours_n)
    return render_template(
        "happened.html",
        rows=rows,
        hours=hours_n or 0,
        household=Household.query.get(hid),
    )


@members_bp.route("/happened/<int:aid>/undo", methods=["POST"])
@login_required
@require_perm("override")
def undo_happened(aid):
    from app.builddb.table_household_activity import HouseholdActivity
    from app.utils.activity import reverse_row

    hid = household_id()
    row = HouseholdActivity.query.filter_by(id=aid, household_id=hid).first_or_404()
    ok, msg = reverse_row(row, by_id=current_user.id)
    flash(msg, "success" if ok else "danger")
    return redirect(url_for("members.happened"))


@members_bp.route("/")
@login_required
def index():
    if current_user.role == "child":
        abort(403)
    return render_template("members.html", **_page_ctx())


@members_bp.route("/sheet/<panel>")
@login_required
def sheet(panel):
    if current_user.role == "child":
        abort(403)
    if panel not in SHEETS:
        abort(404)
    ctx = _page_ctx()
    ctx["sheet_panel"] = panel
    return render_template("members/sheet.html", **ctx)


@members_bp.route("/add", methods=["POST"])
@login_required
@require_perm("members")
def add_person():
    """Leader makes a seat. No Family key. Optional email + calendar."""
    from app.utils.calendar import (
        calendar_target,
        guess_provider,
        normalize_cal_mode,
        normalize_provider,
    )
    from app.utils.household_mail import added_person_email_body, random_login_password
    from app.utils.identity import norm_username, username_taken, valid_username
    from app.utils.keys_ui import stash_issued_key
    from app.utils.mail import send_mail

    hid = household_id()
    household = Household.query.get(hid)
    person_name = (request.form.get("person_name") or "").strip()[:150]
    username = norm_username(request.form.get("username") or "")
    email = (request.form.get("email") or "").strip().lower() or None
    role = (request.form.get("role") or "member").strip().lower()
    if role not in ROLES:
        role = "member"
    if not person_name:
        flash("Name them.", "danger")
        return _after()
    if not username or not valid_username(username):
        flash("Username: start with a letter, then letters, numbers, underscore.", "danger")
        return _after()
    if username_taken(hid, username):
        flash("Someone in this household already uses that username.", "danger")
        return _after()
    if email:
        taken = User.query.filter(User.email == email).first()
        if taken:
            flash("That email is already used.", "danger")
            return _after()
    password = (request.form.get("password") or "").strip() or random_login_password()
    if len(password) < 8:
        flash("Password needs at least 8 characters, or leave it blank and we make one.", "danger")
        return _after()

    cal_email = (request.form.get("calendar_email") or "").strip().lower() or email
    if cal_email and "@" not in cal_email:
        flash("Calendar email doesn't look like an email.", "danger")
        return _after()
    provider = normalize_provider(request.form.get("calendar_provider"), cal_email or "")
    if not (request.form.get("calendar_provider") or "").strip() and cal_email:
        provider = guess_provider(cal_email)
    mode = normalize_cal_mode(request.form.get("calendar_mode"), "auto")

    user = User(
        household_id=hid,
        username=username,
        name=person_name,
        email=email,
        role=role,
        is_leader=False,
        calendar_email=cal_email or None,
        calendar_provider=provider,
        calendar_mode=mode,
        notify_via="both" if mode == "auto" and cal_email else ("calendar" if mode == "auto" else "email"),
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    target = calendar_target(user)
    mailed = False
    mail_msg = ""
    if email and "@" in email:
        body = added_person_email_body(
            household=household,
            login_url=url_for("auth.login", _external=True),
            username=username,
            password=password,
            person_name=person_name,
            calendar_label=target["cal_label"] if target.get("cal_ready") else "",
        )
        ok, mail_msg = send_mail(
            email,
            f"You're on {household.name} — Family OS",
            body,
            household=household,
        )
        mailed = ok
        if not ok:
            flash(mail_msg, "danger")

    hint = f"{person_name} is in as {role}. No Family key — they sign in with the household handle."
    if target.get("cal_ready"):
        hint += f" Calendar: {target['cal_label']}."
    if mailed:
        hint += f" Emailed to {email}."
    elif email:
        hint += f" Copy this — the email to {email} did not send."
    stash_issued_key(
        username,
        f"{person_name} is in",
        hint,
        extra={"username": username, "password": password, "handle": household.handle or ""},
    )
    flash("They're in. Copy the login from the window." if not mailed else f"They're in. {mail_msg}", "success")
    return _after()


@members_bp.route("/invite", methods=["POST"])
@login_required
@require_perm("members")
def invite():
    from app.utils.identity import norm_username, username_taken, valid_username
    from app.utils.household_mail import invite_email_body, random_login_password
    from app.utils.household_vault import unlock_vault, vault_enabled
    from app.utils.keys_ui import stash_issued_key
    from app.utils.mail import send_mail

    hid = household_id()
    household = Household.query.get(hid)
    role = (request.form.get("role") or "member").strip().lower()
    if role not in ROLES:
        role = "member"
    note = (request.form.get("label") or "").strip()[:120]
    email = (request.form.get("email") or "").strip().lower()
    person_name = (request.form.get("person_name") or "").strip()[:150]
    make_login = (request.form.get("make_login") or "") in ("1", "true", "on", "yes")
    username = norm_username(request.form.get("username") or "")
    send_lock = (request.form.get("send_lock") or "").strip()
    code = Invite.new_code()
    db.session.add(
        Invite(
            household_id=hid,
            code=code,
            role=role,
            label=note or person_name or None,
            created_by=current_user.id,
            expires_at=datetime.utcnow() + timedelta(days=14),
        )
    )
    db.session.flush()

    password = ""
    extra = {}
    if make_login:
        if not username or not valid_username(username):
            db.session.rollback()
            flash("To make a login, pick a username: start with a letter.", "danger")
            return _after()
        if username_taken(hid, username):
            db.session.rollback()
            flash("Someone in this household already uses that username.", "danger")
            return _after()
        if email:
            taken = User.query.filter(User.email == email).first()
            if taken:
                db.session.rollback()
                flash("That email is already used.", "danger")
                return _after()
        password = (request.form.get("password") or "").strip() or random_login_password()
        user = User(
            household_id=hid,
            username=username,
            name=person_name or username,
            email=email or None,
            role=role,
            is_leader=False,
        )
        user.set_password(password)
        db.session.add(user)
        extra = {"username": username, "password": password, "handle": household.handle or ""}

    lock_to_send = ""
    if send_lock:
        if vault_enabled(household):
            ok_lock, lock_msg = unlock_vault(household, send_lock)
            if not ok_lock:
                db.session.rollback()
                flash(lock_msg, "danger")
                return _after()
            lock_to_send = send_lock
        else:
            flash("This household has no family lock yet, so none was emailed.", "warning")

    db.session.commit()

    mailed = False
    if email and "@" in email:
        register_url = url_for("auth.register", family=code, email=email, _external=True)
        login_url = url_for("auth.login", _external=True)
        body = invite_email_body(
            household=household,
            code=code,
            role=role,
            register_url=register_url,
            login_url=login_url,
            username=username if make_login else None,
            password=password if make_login else None,
            lock=lock_to_send or None,
            person_name=person_name,
        )
        ok, msg = send_mail(
            email,
            f"You're invited to {household.name} on Family OS",
            body,
            household=household,
        )
        mailed = ok
        if not ok:
            flash(msg, "danger")

    hint = f"Joins this household as {role}. They type their own name. Not a Service key."
    if note:
        hint = f"Note for you: {note}. {hint}"
    if mailed:
        hint += f" Emailed to {email}."
    elif email:
        hint += f" Copy this — the email to {email} did not send."
    stash_issued_key(code, f"Family key {code}", hint, extra=extra or None)
    if mailed:
        flash(f"Family key ready. {msg}", "success")
    else:
        flash("Family key ready — copy it from the window.", "success")
    return _after()


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

    note = (row.label or "").strip()
    hint = "They start their own household and name it themselves. Not yours."
    if note:
        hint = f"Your note: {note}. {hint}"
    stash_issued_key(row.code, "Service key", hint)
    flash("Service key ready — copy it from the window.", "success")
    return _after()


@members_bp.route("/revoke-code", methods=["POST"])
@login_required
@require_perm("members")
def revoke_code():
    from app.utils.access import find_family_invite, find_service_pass, revoke_family_invite, revoke_service_pass

    hid = household_id()
    code = (request.form.get("code") or "").strip()
    fam = find_family_invite(code)
    if fam is not None and int(fam.household_id or 0) == hid:
        if fam.used_at:
            flash(f"{fam.code} was already used. Revoke does not undo a signup.", "warning")
            return _after()
        if fam.revoked_at:
            flash(f"{fam.code} was already revoked.", "info")
            return _after()
        revoke_family_invite(fam)
        flash(f"{fam.code} revoked.", "info")
        return _after()
    srv = find_service_pass(code)
    if srv is not None and int(srv.household_id or 0) == hid:
        if srv.revoked_at:
            flash(f"{srv.code} was already revoked.", "info")
            return _after()
        revoke_service_pass(srv)
        flash(f"{srv.code} revoked.", "info")
        return _after()
    flash("No open key in this household matches that code.", "danger")
    return _after()


@members_bp.route("/invite/<int:iid>/revoke", methods=["POST"])
@login_required
@require_perm("members")
def revoke_invite(iid):
    from app.utils.access import revoke_family_invite

    row = Invite.query.filter_by(id=iid, household_id=household_id()).first_or_404()
    if row.used_at:
        flash("That Family key was already used.", "warning")
        return _after()
    revoke_family_invite(row)
    flash(f"{row.code} revoked.", "info")
    return _after()


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
    return _after()


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
    return _after()


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
    return _after()


@members_bp.route("/<int:user_id>/role", methods=["POST"])
@login_required
@require_perm("members")
def set_role(user_id):
    hid = household_id()
    user = User.query.filter_by(id=user_id, household_id=hid).first_or_404()
    if user.id == current_user.id:
        flash("You cannot change your own role here.", "warning")
        return _after()
    role = (request.form.get("role") or "").strip().lower()
    if role not in ROLES:
        flash("Invalid role.", "danger")
        return _after()
    if role == "child" and user.is_leader:
        from app.utils.leaders import leader_count

        if leader_count(hid) <= 1:
            flash("Promote another leader before making this person a child.", "warning")
            return _after()
        user.is_leader = False
    user.role = role
    db.session.commit()
    flash(f"{user.name} is now {role}.", "success")
    return _after()


@members_bp.route("/<int:user_id>/leader", methods=["POST"])
@login_required
@require_perm("leaders")
def set_leader_flag(user_id):
    hid = household_id()
    if not current_user.is_leader:
        flash("Only household leaders can change who the leaders are.", "warning")
        return _after()
    user = User.query.filter_by(id=user_id, household_id=hid).first_or_404()
    make = (request.form.get("leader") or "").strip() in ("1", "true", "on", "yes")
    from app.utils.leaders import set_leader

    ok, msg = set_leader(user, make)
    flash(msg, "success" if ok else "danger")
    return _after()


@members_bp.route("/<int:user_id>/reset", methods=["POST"])
@login_required
@require_perm("leaders")
def send_member_reset(user_id):
    hid = household_id()
    if not current_user.is_leader:
        flash("Only household leaders can send a reset for someone here.", "warning")
        return _after()
    user = User.query.filter_by(id=user_id, household_id=hid, is_active=True).first_or_404()
    from app.utils.passwords import issue_reset, send_reset_email

    token = issue_reset(user, requested_by=current_user.id)
    if not token:
        flash(f"{user.name} needs an email on this household first.", "warning")
        return _after()
    ok, msg = send_reset_email(user, token)
    flash(msg if not ok else f"Reset link handed to the mail server for {user.email}. {msg}", "success" if ok else "danger")
    return _after()


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
    return _after()


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
            return _after()
    user.email = email
    if email and not (user.calendar_email or "").strip():
        user.calendar_email = email
    db.session.commit()
    flash("Email updated.", "success")
    return _after()


@members_bp.route("/<int:user_id>/calendar", methods=["POST"])
@login_required
@require_perm("members")
def set_member_calendar(user_id):
    from app.utils.calendar import calendar_target, guess_provider, normalize_cal_mode, normalize_provider

    hid = household_id()
    user = User.query.filter_by(id=user_id, household_id=hid).first_or_404()
    if (request.form.get("clear_calendar") or "") == "1":
        user.calendar_email = None
        user.calendar_mode = "manual"
        db.session.commit()
        flash(f"Calendar removed for {user.name}.", "success")
        return _after()
    cal_email = (request.form.get("calendar_email") or "").strip().lower() or None
    if cal_email and "@" not in cal_email:
        flash("Calendar email doesn't look like an email.", "danger")
        return _after()
    provider = normalize_provider(request.form.get("calendar_provider"), cal_email or "")
    if not (request.form.get("calendar_provider") or "").strip() and cal_email:
        provider = guess_provider(cal_email)
    mode = normalize_cal_mode(request.form.get("calendar_mode"), "auto")
    user.calendar_email = cal_email
    user.calendar_provider = provider
    user.calendar_mode = mode
    if mode == "auto" and cal_email:
        if (user.notify_via or "") == "email":
            user.notify_via = "both"
        elif (user.notify_via or "") not in ("email", "calendar", "both"):
            user.notify_via = "calendar"
    db.session.commit()
    target = calendar_target(user)
    flash(
        f"Calendar for {user.name}: {target['cal_label']}."
        if target.get("cal_ready")
        else f"Calendar for {user.name} saved. Name an email to auto-add.",
        "success",
    )
    return _after()


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
    flash("Household AI key saved. Yours only — Family OS never uses the owner's key.", "success")
    return _after()


@members_bp.route("/ai/test", methods=["POST"])
@login_required
@require_perm("settings")
def test_ai():
    from app.utils.ai import ping_ai

    h = Household.query.get(household_id())
    ok, msg = ping_ai(h, household_only=True)
    flash(msg, "success" if ok else "danger")
    return _after()


@members_bp.route("/rename", methods=["POST"])
@login_required
@require_perm("settings")
def rename_household():
    name = (request.form.get("name") or "").strip()
    h = Household.query.get(household_id())
    if not name:
        flash("Name your household. We will not name it for you.", "danger")
        return _after()
    h.name = name
    db.session.commit()
    flash("Household name saved.", "success")
    return _after()


@members_bp.route("/handle", methods=["POST"])
@login_required
@require_perm("settings")
def save_handle():
    from app.utils.identity import valid_handle, norm_handle

    h = Household.query.get(household_id())
    raw = norm_handle(request.form.get("handle") or "")
    if not valid_handle(raw):
        flash("Handle: start with a letter, letters and numbers only. This is how you sign in.", "danger")
        return _after()
    taken = Household.query.filter(Household.handle == raw, Household.id != h.id).first()
    if taken:
        flash("That household handle is taken. Try another.", "danger")
        return _after()
    h.handle = raw
    db.session.commit()
    flash(f"Household handle is {raw}. Sign in with that plus your username.", "success")
    return _after()


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
        return _after()
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
        return _after()
    if username_taken(hid, raw, exclude_id=user.id):
        flash("Someone in this household already uses that username.", "danger")
        return _after()
    user.username = raw
    db.session.commit()
    flash(f"{user.name} signs in as {raw}.", "success")
    return _after()


@members_bp.route("/places", methods=["POST"])
@login_required
@require_perm("settings")
def save_places():
    from app.utils.places import save_places as _save

    h = Household.query.get(household_id())
    names = _save(h, request.form.get("places") or "")
    db.session.commit()
    flash(f"Saved {len(names)} places.", "success")
    return _after()


@members_bp.route("/vault", methods=["POST"])
@login_required
@require_perm("settings")
def save_vault():
    from app.utils.household_vault import set_vault, unlock_vault

    h = Household.query.get(household_id())
    lock = (request.form.get("family_lock") or "").strip()
    ok, msg = set_vault(h, lock)
    if ok:
        unlock_vault(h, lock)
    flash(msg, "success" if ok else "danger")
    return _after()


@members_bp.route("/mail", methods=["POST"])
@login_required
@require_perm("settings")
def save_mail():
    from app.utils.household_mail import save_household_mail

    h = Household.query.get(household_id())
    saved = save_household_mail(
        h,
        enabled=(request.form.get("mail_enabled") or "") in ("1", "true", "on", "yes"),
        from_name=request.form.get("from_name") or "",
        from_email=request.form.get("from_email") or "",
        reply_to=request.form.get("reply_to") or "",
        smtp_host=request.form.get("smtp_host") or "",
        smtp_port=request.form.get("smtp_port") or 587,
        smtp_encryption=request.form.get("smtp_encryption") or "tls",
        smtp_username=request.form.get("smtp_username") or "",
        smtp_password=request.form.get("smtp_password") or "",
        clear_password=(request.form.get("mail_clear_password") or "") == "1",
    )
    flash("Household email saved. Invites and reminders from this house use it when it is on.", "success")
    if saved.get("smtp_fix"):
        flash(saved["smtp_fix"], "info")
    return _after()


@members_bp.route("/mail/test", methods=["POST"])
@login_required
@require_perm("settings")
def test_mail():
    from app.utils.mail import send_mail

    h = Household.query.get(household_id())
    to = (request.form.get("to") or current_user.email or "").strip()
    ok, msg = send_mail(
        to,
        "Family OS household mail test",
        "This household's mailbox sent this. If you got it, your SMTP is working.",
        household=h,
    )
    flash(msg, "success" if ok else "danger")
    return _after()
