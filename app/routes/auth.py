from datetime import datetime, timedelta, timezone
from flask import Blueprint, render_template, request, flash, redirect, url_for, session
from flask_login import login_user, logout_user, login_required, current_user

from app.builddb.builddb import db
from app.builddb.table_users import User, ROLES
from app.builddb.table_households import Household
from app.utils.access import (
    bootstrap_open,
    can_enter_service,
    consume_service_pass,
    email_is_trusted,
    family_invite_ok,
)

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def _stay_signed_in(user):
    """PWA / phone: keep this device signed in unless they uncheck it."""
    vals = request.form.getlist("remember")
    raw = (vals[-1] if vals else "1").strip().lower()
    remember = raw not in ("0", "false", "off", "no")
    session.permanent = True
    dur = timedelta(days=400) if remember else None
    login_user(user, remember=remember, duration=dur)


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("home.home"))
    if request.method == "POST":
        ident = (request.form.get("username") or "").strip()
        household = (request.form.get("household") or "").strip()
        password = request.form.get("password") or ""
        if not ident or not password:
            flash("Enter your household, username, and password.", "danger")
            return render_template("auth/login.html")
        from app.utils.identity import find_login

        user = find_login(ident, household)
        if user is None and ident and not household:
            from sqlalchemy import func

            n = User.query.filter(func.lower(User.username) == ident.lower()).count()
            if n > 1:
                flash("More than one household has that username. Type your household handle too.", "danger")
                return render_template("auth/login.html")
        if user and user.account_locked_until:
            lock = user.account_locked_until
            if lock.tzinfo is None:
                lock = lock.replace(tzinfo=timezone.utc)
            if lock > datetime.now(timezone.utc):
                flash("Account temporarily locked. Try again later.", "danger")
                return render_template("auth/login.html")
        if user and user.is_active and user.check_password(password):
            household = getattr(user, "household", None)
            if household is not None and not bool(getattr(household, "is_active", True)):
                flash("This household is paused. Ask the household leader.", "warning")
                return render_template("auth/login.html")
            user.failed_login_attempts = 0
            user.account_locked_until = None
            user.last_login_at = _utcnow()
            db.session.commit()
            family_lock = (request.form.get("family_lock") or "").strip()
            if household is not None:
                from app.utils.household_vault import unlock_vault, vault_enabled

                if vault_enabled(household) and family_lock:
                    ok_lock, lock_msg = unlock_vault(household, family_lock)
                    if not ok_lock:
                        flash(lock_msg, "danger")
                        return render_template("auth/login.html")
            try:
                from poweredbytop.utils.helpers import get_real_ip
                from poweredbytop.reputation.scorer import update_reputation_on_login_attempt

                update_reputation_on_login_attempt(get_real_ip(), user.username, success=True)
            except Exception:
                pass
            _stay_signed_in(user)
            from app.utils.dashboard import start_url

            resp = redirect(start_url(user))
            try:
                from app.utils.themes import normalize, stamp_theme_cookie

                extra = user.extra_data if isinstance(user.extra_data, dict) else {}
                stamp_theme_cookie(resp, normalize((extra or {}).get("theme")))
            except Exception:
                pass
            return resp
        if user:
            user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
            if user.failed_login_attempts >= 5:
                user.account_locked_until = _utcnow() + timedelta(minutes=15)
            db.session.commit()
        try:
            from poweredbytop.utils.helpers import get_real_ip
            from poweredbytop.reputation.scorer import update_reputation_on_login_attempt

            update_reputation_on_login_attempt(get_real_ip(), ident or "unknown", success=False)
        except Exception:
            pass
        flash("Invalid household, username, or password.", "danger")
    return render_template("auth/login.html")


def _register_ctx(**extra):
    ctx = {
        "invite": extra.get("invite") or "",
        "service_key": extra.get("service_key") or "",
        "bootstrap": bootstrap_open(),
        "trusted": extra.get("trusted", False),
    }
    ctx.update(extra)
    return ctx


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("home.home"))
    invite_prefill = (
        request.args.get("family")
        or request.args.get("invite")
        or request.form.get("family_key")
        or request.form.get("invite_code")
        or ""
    ).strip()
    service_prefill = (
        request.args.get("service")
        or request.form.get("service_key")
        or ""
    ).strip()
    if request.method != "POST":
        email_q = (request.args.get("email") or "").strip().lower()
        return render_template(
            "auth/register.html",
            **_register_ctx(
                invite=invite_prefill,
                service_key=service_prefill,
                trusted=email_is_trusted(email_q),
            ),
        )

    from app.utils.identity import (
        norm_username,
        unique_handle,
        username_taken,
        valid_username,
    )

    name = (request.form.get("name") or "").strip()
    username = norm_username(request.form.get("username") or "")
    email = (request.form.get("email") or "").strip().lower() or None
    password = request.form.get("password") or ""
    household_name = (request.form.get("household_name") or "").strip()
    family_key = (
        request.form.get("family_key") or request.form.get("invite_code") or invite_prefill
    ).strip()
    service_key = (request.form.get("service_key") or service_prefill).strip()
    ctx = _register_ctx(
        invite=family_key,
        service_key=service_key,
        trusted=email_is_trusted(email),
        name=name,
        username=username,
        email=email or "",
        household_name=household_name,
        family_lock=(request.form.get("family_lock") or "").strip(),
    )
    if not name or not username or not password:
        flash("Name, username, and password are required.", "danger")
        return render_template("auth/register.html", **ctx)
    if not valid_username(username):
        flash("Username: start with a letter, then letters, numbers, underscore. Unique in your household.", "danger")
        return render_template("auth/register.html", **ctx)
    if email and User.query.filter_by(email=email).first():
        flash("That email is already registered.", "danger")
        return render_template("auth/register.html", **ctx)

    allowed, reason, bits = can_enter_service(
        email=email, service_key=service_key, family_key=family_key
    )
    if not allowed:
        flash(reason, "danger")
        return render_template("auth/register.html", **ctx)

    household = None
    role = "admin"
    invite = bits.get("invite")
    make_leader = False
    if invite is not None:
        ok, err = family_invite_ok(invite)
        if not ok:
            flash(err, "danger")
            return render_template("auth/register.html", **ctx)
        household = Household.query.get(invite.household_id)
        role = invite.role if invite.role in ROLES else "member"
        from app.utils.leaders import leader_count

        if leader_count(household.id) == 0 and role != "child":
            make_leader = True
        if username_taken(household.id, username):
            flash("Someone in that household already uses that username. Pick another.", "danger")
            return render_template("auth/register.html", **ctx)
    else:
        if not household_name:
            flash("Name your household however you want.", "danger")
            return render_template("auth/register.html", **ctx)
        household = Household(name=household_name, handle=unique_handle(household_name))
        household.rotate_invite_code()
        db.session.add(household)
        db.session.flush()
        make_leader = True
        family_lock = (request.form.get("family_lock") or "").strip()
        if family_lock:
            from app.utils.household_vault import set_vault, unlock_vault

            ok_lock, lock_msg = set_vault(household, family_lock, commit=False)
            if not ok_lock:
                db.session.rollback()
                flash(lock_msg, "danger")
                return render_template("auth/register.html", **ctx)
            unlock_vault(household, family_lock)

    user = User(
        household_id=household.id,
        username=username,
        name=name,
        email=email,
        role=role,
        is_leader=make_leader,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.flush()
    if invite:
        invite.used_by = user.id
        invite.used_at = _utcnow()
    if bits.get("pass") is not None:
        consume_service_pass(bits["pass"])
    db.session.commit()
    _stay_signed_in(user)
    family_lock = (request.form.get("family_lock") or "").strip()
    if family_lock:
        from app.utils.household_vault import unlock_vault, vault_enabled

        if vault_enabled(household):
            ok_lock, lock_msg = unlock_vault(household, family_lock)
            if not ok_lock:
                flash(lock_msg, "warning")
    handle = household.handle or ""
    if invite is not None:
        flash(f"You're in, {user.name}. Sign in as {user.username}.", "success")
    else:
        flash(
            f"You're in, {user.name}. Your username is {user.username}"
            + (f". Household handle: {handle}." if handle else "."),
            "success",
        )
    return redirect(url_for("home.home"))


@auth_bp.route("/logout")
@login_required
def logout():
    try:
        from app.utils.household_vault import lock_session

        lock_session()
    except Exception:
        pass
    logout_user()
    flash("Signed out.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/vault", methods=["GET", "POST"])
@login_required
def vault():
    from app.utils.household_vault import (
        FORMAT_HINT,
        unlock_vault,
        vault_enabled,
        vault_hint,
        vault_unlocked,
    )

    household = getattr(current_user, "household", None)
    if household is None or not vault_enabled(household):
        return redirect(url_for("home.home"))
    if request.method == "POST":
        ok, msg = unlock_vault(household, request.form.get("family_lock") or "")
        flash(msg, "success" if ok else "danger")
        if ok:
            from app.utils.dashboard import start_url

            nxt = (request.args.get("next") or "").strip() or start_url(current_user)
            if not nxt.startswith("/"):
                nxt = start_url(current_user)
            return redirect(nxt)
    return render_template(
        "auth/vault.html",
        hint=vault_hint(household),
        format_hint=FORMAT_HINT,
        unlocked=vault_unlocked(household),
    )


@auth_bp.route("/forgot", methods=["GET", "POST"])
def forgot():
    if current_user.is_authenticated:
        return redirect(url_for("home.home"))
    from app.utils.passwords import SAME_MSG, find_user_for_forgot, issue_reset, send_reset_email

    if request.method == "POST":
        ident = (request.form.get("username") or "").strip()
        household = (request.form.get("household") or "").strip()
        user = find_user_for_forgot(ident, household)
        if user is not None:
            token = issue_reset(user, requested_by=user.id)
            if token:
                ok, err = send_reset_email(user, token)
                if not ok:
                    print(f"Family OS reset mail failed: {err}", flush=True)
        flash(SAME_MSG, "info")
        return redirect(url_for("auth.forgot"))
    return render_template("auth/forgot.html")


@auth_bp.route("/reset/<token>", methods=["GET", "POST"])
def reset_password(token):
    from app.utils.passwords import consume_token, mark_used

    row = consume_token(token)
    if row is None:
        flash("That reset link is invalid or expired. Ask a household leader, or try again.", "danger")
        return redirect(url_for("auth.forgot"))
    user = row._user
    if request.method == "POST":
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""
        if len(password) < 8:
            flash("Password needs at least 8 characters.", "danger")
            return render_template("auth/reset.html", token=token, name=user.name)
        if password != confirm:
            flash("Passwords do not match.", "danger")
            return render_template("auth/reset.html", token=token, name=user.name)
        user.set_password(password)
        user.failed_login_attempts = 0
        user.account_locked_until = None
        db.session.commit()
        mark_used(row)
        flash("Password updated. Sign in.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/reset.html", token=token, name=user.name)


@auth_bp.route("/password", methods=["POST"])
@login_required
def change_own_password():
    current = request.form.get("current_password") or ""
    new = request.form.get("new_password") or ""
    confirm = request.form.get("confirm_password") or ""
    if not current_user.check_password(current):
        flash("Current password is wrong.", "danger")
        return redirect(url_for("appearance.picker"))
    if len(new) < 8:
        flash("New password needs at least 8 characters.", "danger")
        return redirect(url_for("appearance.picker"))
    if new != confirm:
        flash("New passwords do not match.", "danger")
        return redirect(url_for("appearance.picker"))
    current_user.set_password(new)
    db.session.commit()
    flash("Your password is updated.", "success")
    return redirect(url_for("appearance.picker"))
