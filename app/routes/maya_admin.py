"""Owner-only "Maya permissions" checklist.

Only a signed-in, non-bot household leader can open or save this page. The
bot API never routes here (bots have no browser session and are refused
anyway). Saves are live: the Maya API reads the switches from the DB on
every request. High-risk switches need the owner's password or 2FA code to
go from off to on.
"""
from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.builddb.builddb import db
from app.utils import maya_perms
from app.utils.household import household_id

maya_admin_bp = Blueprint("maya_admin", __name__, url_prefix="/maya-permissions")


def _owner_only():
    if not maya_perms.is_owner(current_user) or maya_perms.is_maya(current_user):
        abort(403)


def _bots(hid):
    from app.builddb.table_users import User

    return User.query.filter_by(household_id=hid, is_active=True, is_bot=True).order_by(User.name.asc()).all()


@maya_admin_bp.route("/", methods=["GET"])
@login_required
def index():
    from app.builddb.table_maya_bot import HouseholdTrash, MayaBotPermLog
    from app.builddb.table_users import User

    _owner_only()
    hid = household_id()
    acct = maya_perms.maya_account(hid)
    maya = User.query.filter_by(id=acct.user_id, household_id=hid).first() if acct else None
    state = maya_perms.perm_state(hid, maya.id) if maya else {}
    expiry = maya_perms.perm_expiry(hid, maya.id) if maya else {}
    log = (MayaBotPermLog.query.filter_by(household_id=hid).order_by(MayaBotPermLog.id.desc()).limit(40).all())
    trash = (HouseholdTrash.query.filter_by(household_id=hid)
             .filter(HouseholdTrash.restored_at.is_(None), HouseholdTrash.purged_at.is_(None))
             .order_by(HouseholdTrash.id.desc()).limit(50).all())
    names = {u.id: (u.name or u.username) for u in User.query.filter_by(household_id=hid).all()}
    return render_template(
        "maya_permissions.html",
        groups=maya_perms.groups(),
        state=state,
        expiry=expiry,
        remaining=maya_perms.remaining_text,
        units=list(maya_perms.EXPIRY_UNITS),
        maya=maya,
        acct=acct,
        bots=_bots(hid),
        hard_limits=maya_perms.HARD_LIMITS,
        log=log,
        trash=trash,
        names=names,
    )


@maya_admin_bp.route("/account", methods=["POST"])
@login_required
def set_account():
    from app.builddb.table_users import User

    _owner_only()
    hid = household_id()
    uid = request.form.get("user_id", type=int)
    user = User.query.filter_by(id=uid, household_id=hid, is_active=True).first() if uid else None
    ok, msg = maya_perms.set_maya(hid, user, by_user=current_user)
    if ok:
        db.session.commit()
    else:
        db.session.rollback()
    flash(msg, "success" if ok else "danger")
    return redirect(url_for("maya_admin.index"))


@maya_admin_bp.route("/", methods=["POST"])
@login_required
def save():
    from app.builddb.table_users import User

    _owner_only()
    hid = household_id()
    acct = maya_perms.maya_account(hid)
    maya = User.query.filter_by(id=acct.user_id, household_id=hid).first() if acct else None
    if maya is None:
        flash("Pick Maya's bot account first.", "warning")
        return redirect(url_for("maya_admin.index"))
    if maya.id == current_user.id:
        abort(403)
    on = set(request.form.getlist("perm"))
    wanted = {pid: (pid in on) for pid in maya_perms.CATALOG_BY_ID}
    # Auto-off timers: exp_unit_<perm> = keep | none | hours | days | weeks | months, exp_n_<perm> = number.
    expiry, bad = {}, []
    for pid in on:
        perm = maya_perms.CATALOG_BY_ID.get(pid)
        if perm is None:
            continue
        unit = (request.form.get(f"exp_unit_{pid}") or "keep").strip().lower()
        if unit == "keep":
            continue
        if unit in ("none", "") and perm["high_risk"]:
            bad.append(perm["label"])
            continue  # save_state falls back to the 24-hour default
        try:
            expiry[pid] = maya_perms.parse_expiry(unit, request.form.get(f"exp_n_{pid}") or "1")
        except ValueError:
            bad.append(perm["label"])
    if bad:
        flash("Timer not understood for: " + ", ".join(bad) + ". High-risk switches got the 24-hour default.", "warning")
    current = maya_perms.perm_state(hid, maya.id)
    needs_confirm = any(
        wanted[p] and not current.get(p) and maya_perms.CATALOG_BY_ID[p]["high_risk"] for p in wanted
    ) or any(maya_perms.CATALOG_BY_ID[p]["high_risk"] for p in expiry)
    confirmed = None
    if needs_confirm:
        confirmed = maya_perms.confirm_owner(
            current_user,
            password=request.form.get("confirm_password") or "",
            code=request.form.get("confirm_code") or "",
        )
    ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip()[:64]
    changed, refused = maya_perms.save_state(hid, maya, wanted, owner=current_user, confirmed_with=confirmed, ip=ip,
                                             expiry=expiry)
    if refused:
        flash(
            "High-risk switches stayed OFF: "
            + ", ".join(maya_perms.CATALOG_BY_ID[p]["label"] for p in refused)
            + ". Enter your password or 2FA code to turn them on.",
            "warning",
        )
    flash(f"Saved. {len(changed)} change(s), live now." if changed else "No changes.", "success")
    return redirect(url_for("maya_admin.index"))


@maya_admin_bp.route("/trash/<int:trash_id>/restore", methods=["POST"])
@login_required
def restore(trash_id):
    from app.builddb.table_maya_bot import HouseholdTrash
    from app.utils import maya_store

    _owner_only()
    entry = HouseholdTrash.query.filter_by(id=trash_id, household_id=household_id()).first_or_404()
    ok, msg = maya_store.restore(entry, actor_id=current_user.id)
    if not ok:
        db.session.rollback()
    flash(msg, "success" if ok else "danger")
    return redirect(url_for("maya_admin.index"))
