from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash
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
@require_perm("members")
def index():
    hid = household_id()
    members = User.query.filter_by(household_id=hid).order_by(User.name.asc()).all()
    invites = (
        Invite.query.filter_by(household_id=hid)
        .filter(Invite.used_at.is_(None))
        .order_by(Invite.created_at.desc())
        .all()
    )
    household = Household.query.get(hid)
    return render_template(
        "members.html", members=members, invites=invites, household=household, roles=ROLES
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
    flash(f"Invite code {code} — role {role}. Share it with family.", "success")
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
    user.role = role
    db.session.commit()
    flash(f"{user.name} is now {role}.", "success")
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
