from datetime import datetime, timedelta, timezone
from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_user, logout_user, login_required, current_user

from app.builddb.builddb import db
from app.builddb.table_users import User, ROLES
from app.builddb.table_households import Household
from app.builddb.table_invites import Invite

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("home.home"))
    if request.method == "POST":
        ident = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        if not ident or not password:
            flash("Enter your username or email and password.", "danger")
            return render_template("auth/login.html")
        user = User.query.filter(
            (User.username == ident) | (User.email == ident)
        ).first()
        if user and user.account_locked_until:
            lock = user.account_locked_until
            if lock.tzinfo is None:
                lock = lock.replace(tzinfo=timezone.utc)
            if lock > datetime.now(timezone.utc):
                flash("Account temporarily locked. Try again later.", "danger")
                return render_template("auth/login.html")
        if user and user.is_active and user.check_password(password):
            user.failed_login_attempts = 0
            user.account_locked_until = None
            user.last_login_at = _utcnow()
            db.session.commit()
            try:
                from poweredbytop.utils.helpers import get_real_ip
                from poweredbytop.reputation.scorer import update_reputation_on_login_attempt

                update_reputation_on_login_attempt(get_real_ip(), user.username, success=True)
            except Exception:
                pass
            login_user(user)
            resp = redirect(url_for("home.home"))
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
        flash("Invalid username or password.", "danger")
    return render_template("auth/login.html")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("home.home"))
    invite_prefill = (request.args.get("invite") or "").strip()
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip() or None
        password = request.form.get("password") or ""
        household_name = (request.form.get("household_name") or "").strip()
        invite_code = (request.form.get("invite_code") or "").strip().upper()
        if not name or not username or not password:
            flash("Name, username, and password are required.", "danger")
            return render_template("auth/register.html", invite=invite_code or invite_prefill)
        if User.query.filter_by(username=username).first():
            flash("That username is already taken.", "danger")
            return render_template("auth/register.html", invite=invite_code or invite_prefill)
        if email and User.query.filter_by(email=email).first():
            flash("That email is already registered.", "danger")
            return render_template("auth/register.html", invite=invite_code or invite_prefill)

        household = None
        role = "admin"
        invite = None
        if invite_code:
            invite = Invite.query.filter_by(code=invite_code).first()
            if invite is None or invite.used_at:
                flash("Invite code is invalid or already used.", "danger")
                return render_template("auth/register.html", invite=invite_code)
            if invite.expires_at and invite.expires_at < _utcnow():
                flash("Invite code has expired.", "danger")
                return render_template("auth/register.html", invite=invite_code)
            household = Household.query.get(invite.household_id)
            role = invite.role if invite.role in ROLES else "member"
        else:
            if not household_name:
                flash("Give your household a name, or join with an invite code.", "danger")
                return render_template("auth/register.html", invite=invite_prefill)
            household = Household(name=household_name)
            household.rotate_invite_code()
            db.session.add(household)
            db.session.flush()

        user = User(
            household_id=household.id,
            username=username,
            name=name,
            email=email,
            role=role,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        if invite:
            invite.used_by = user.id
            invite.used_at = _utcnow()
        db.session.commit()
        login_user(user)
        flash(f"Welcome to {household.name}.", "success")
        return redirect(url_for("home.home"))
    return render_template("auth/register.html", invite=invite_prefill)


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Signed out.", "info")
    return redirect(url_for("auth.login"))
