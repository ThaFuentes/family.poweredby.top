"""Owner / platform console. You are not a household user."""
from __future__ import annotations

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from app.builddb.builddb import db
from app.builddb.table_households import Household
from app.builddb.table_platform_audit import PlatformAudit
from app.builddb.table_platform_owners import PlatformOwner
from app.utils.ai import DEFAULT_MODEL, public_ai_config, ping_ai, normalize_provider
from app.utils.leaders import fleet_cards
from app.utils.mail import mail_config, send_mail
from app.utils.platform_auth import (
    consume_owner_invite,
    current_owner,
    find_owner,
    find_owner_invite,
    is_owner,
    login_owner,
    logout_owner,
    mark_login_failure,
    mark_login_success,
    mint_owner_invite,
    needs_setup,
    owner_count,
    owner_invite_ok,
    owner_is_locked,
    require_owner,
    revoke_owner_invite,
)
from app.utils.platform_settings import audit, mask_secret, set_setting

platform_bp = Blueprint("platform", __name__, url_prefix="/platform")


def _ip():
    try:
        from poweredbytop.utils.helpers import get_real_ip

        return get_real_ip()
    except Exception:
        return (request.remote_addr or "")[:64]


def _safe_next():
    nxt = request.args.get("next") or request.form.get("next") or url_for("platform.home")
    if not str(nxt).startswith("/platform"):
        return url_for("platform.home")
    return nxt


def _owner_id():
    row = current_owner()
    return None if row is None else row.id


def _create_owner_form_error(username, email, password, confirm):
    if len(username) < 2:
        return "Pick a username."
    if PlatformOwner.query.filter_by(username=username).first():
        return "That username is taken."
    if "@" not in email:
        return "Need an email."
    if PlatformOwner.query.filter_by(email=email).first():
        return "That email is already an owner."
    if len(password) < 8:
        return "Password needs at least 8 characters."
    if password != confirm:
        return "Passwords do not match."
    return None


@platform_bp.route("/login", methods=["GET", "POST"])
def login():
    if is_owner():
        return redirect(url_for("platform.home"))
    setup = needs_setup()
    owner_key = (request.values.get("owner_key") or request.values.get("owner") or "").strip()
    invite = find_owner_invite(owner_key) if owner_key else None
    joining = (not setup) and bool(owner_key)
    if request.method != "POST":
        join_err = None
        if joining:
            ok, join_err = owner_invite_ok(invite)
            if not ok:
                joining = False
        return render_template(
            "platform/login.html",
            setup=setup,
            joining=joining,
            owner_key=owner_key if joining else "",
            error=join_err if joining is False and owner_key else None,
        )

    if setup or joining:
        username = (request.form.get("username") or "").strip()
        name = (request.form.get("name") or "").strip() or username
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""
        err = _create_owner_form_error(username, email, password, confirm)
        invite_row = None
        if not err and setup and owner_count() > 0:
            err = "Someone already took the desk. Sign in, or paste an owner key."
        if not err and not setup:
            invite_row = find_owner_invite(owner_key)
            ok, msg = owner_invite_ok(invite_row)
            if not ok:
                err = msg
        if err:
            return render_template(
                "platform/login.html",
                setup=setup,
                joining=not setup,
                owner_key=owner_key,
                error=err,
            ), 400
        owner = PlatformOwner(username=username, name=name, email=email, is_active=True)
        owner.set_password(password)
        db.session.add(owner)
        if invite_row is not None:
            consume_owner_invite(invite_row)
        db.session.commit()
        login_owner(owner)
        audit(
            "owner.first" if setup else "owner.join",
            owner_id=owner.id,
            ip=_ip(),
            detail={"username": username, "key": (invite_row.code if invite_row else None)},
        )
        flash("You're on the owner desk. This is not a household login.", "success")
        return redirect(_safe_next())

    ident = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    owner = find_owner(ident)
    if owner and owner_is_locked(owner):
        return render_template(
            "platform/login.html",
            setup=False,
            joining=False,
            owner_key="",
            error="Account temporarily locked. Try again later.",
        ), 429
    if owner and owner.is_active and owner.check_password(password):
        mark_login_success(owner)
        login_owner(owner)
        audit("owner.login", owner_id=owner.id, ip=_ip())
        return redirect(_safe_next())
    mark_login_failure(owner)
    audit("owner.login_fail", owner_id=getattr(owner, "id", None), ip=_ip())
    return render_template(
        "platform/login.html",
        setup=False,
        joining=False,
        owner_key="",
        error="Wrong username or password.",
    ), 401


@platform_bp.route("/logout", methods=["GET", "POST"])
def logout():
    oid = _owner_id()
    logout_owner()
    if oid:
        audit("owner.logout", owner_id=oid, ip=_ip())
    flash("Signed out of platform.", "info")
    return redirect(url_for("platform.login"))


@platform_bp.route("/")
@require_owner
def home():
    cards = fleet_cards()
    active = sum(1 for c in cards if c["is_active"])
    mail = mail_config()
    ai = public_ai_config()
    recent = (
        PlatformAudit.query.order_by(PlatformAudit.created_at.desc()).limit(12).all()
    )
    return render_template(
        "platform/home.html",
        owner=current_owner(),
        household_count=len(cards),
        active_count=active,
        mail=mail,
        ai=ai,
        recent=recent,
    )


@platform_bp.route("/households")
@require_owner
def households():
    return render_template(
        "platform/households.html",
        owner=current_owner(),
        cards=fleet_cards(),
    )


@platform_bp.route("/access", methods=["GET", "POST"])
@require_owner
def access():
    from app.builddb.table_service_passes import ServicePass
    from app.builddb.table_trusted_emails import TrustedEmail
    from app.utils.access import (
        add_trusted_email,
        mint_service_pass,
        revoke_family_invite,
        revoke_key_by_code,
        revoke_service_pass,
    )

    if request.method == "POST":
        kind = (request.form.get("kind") or "").strip()
        if kind == "service":
            row = mint_service_pass(
                created_by=None,
                household_id=None,
                label=(request.form.get("label") or "platform").strip(),
                max_uses=request.form.get("max_uses") or 3,
                days=request.form.get("days") or 30,
            )
            audit("access.service_mint", owner_id=_owner_id(), ip=_ip(), detail={"code": row.code})
            from app.utils.keys_ui import stash_issued_key

            stash_issued_key(
                row.code,
                "Service key",
                "Gets someone onto Family OS. Does not put them in a household.",
            )
            flash("Service key ready — copy it from the window.", "success")
        elif kind == "trusted":
            ok, msg, _row = add_trusted_email(
                email=request.form.get("email") or "",
                added_by=None,
                household_id=None,
                note=request.form.get("note") or "platform",
            )
            audit("access.trusted", owner_id=_owner_id(), ip=_ip(), detail={"ok": ok})
            flash(msg, "success" if ok else "danger")
        elif kind == "revoke":
            kid = request.form.get("id") or ""
            if str(kid).isdigit():
                row = ServicePass.query.get(int(kid))
                if row:
                    revoke_service_pass(row)
                    audit("access.service_revoke", owner_id=_owner_id(), ip=_ip(), detail={"code": row.code})
                    flash(f"{row.code} revoked.", "info")
        elif kind == "revoke_family":
            kid = request.form.get("id") or ""
            if str(kid).isdigit():
                from app.builddb.table_invites import Invite

                row = Invite.query.get(int(kid))
                if row:
                    if row.used_at:
                        flash(f"{row.code} was already used. Revoke does not undo a signup.", "warning")
                    else:
                        revoke_family_invite(row)
                        audit("access.family_revoke", owner_id=_owner_id(), ip=_ip(), detail={"code": row.code})
                        flash(f"{row.code} revoked.", "info")
        elif kind == "revoke_code":
            code = (request.form.get("code") or "").strip()
            ok, msg, knd = revoke_key_by_code(code)
            if not ok and not knd:
                from app.utils.platform_auth import find_owner_invite

                inv = find_owner_invite(code)
                if inv is not None:
                    if inv.revoked_at:
                        ok, msg, knd = True, f"{inv.code} was already revoked.", "owner"
                    else:
                        revoke_owner_invite(inv)
                        ok, msg, knd = True, f"{inv.code} revoked.", "owner"
            if ok:
                audit(
                    "access.revoke_code",
                    owner_id=_owner_id(),
                    ip=_ip(),
                    detail={"kind": knd, "code": (code or "")[:40]},
                )
            flash(msg, "info" if ok else "danger")
        elif kind == "untrust":
            tid = request.form.get("id") or ""
            if str(tid).isdigit():
                row = TrustedEmail.query.get(int(tid))
                if row:
                    addr = row.email
                    db.session.delete(row)
                    db.session.commit()
                    audit("access.untrust", owner_id=_owner_id(), ip=_ip(), detail={"email": addr})
                    flash(f"{addr} removed from the trusted list.", "info")
        elif kind == "owner":
            row = mint_owner_invite(
                created_by=_owner_id(),
                label=(request.form.get("label") or "").strip(),
                max_uses=request.form.get("max_uses") or 1,
                days=request.form.get("days") or 14,
            )
            audit("access.owner_mint", owner_id=_owner_id(), ip=_ip(), detail={"code": row.code})
            from app.utils.keys_ui import stash_issued_key

            stash_issued_key(
                row.code,
                "Owner key",
                "They open /platform/ and paste it. Not a household key.",
            )
            flash("Owner key ready — copy it from the window.", "success")
        elif kind == "revoke_owner":
            kid = request.form.get("id") or ""
            if str(kid).isdigit():
                from app.builddb.table_platform_invites import PlatformInvite

                row = PlatformInvite.query.get(int(kid))
                if row:
                    revoke_owner_invite(row)
                    audit("access.owner_revoke", owner_id=_owner_id(), ip=_ip(), detail={"code": row.code})
                    flash(f"{row.code} revoked.", "info")
        return redirect(url_for("platform.access"))
    from app.builddb.table_invites import Invite
    from app.builddb.table_platform_invites import PlatformInvite
    from app.utils.keys_ui import pop_issued_key

    family_keys = (
        Invite.query.filter(Invite.used_at.is_(None))
        .filter(Invite.revoked_at.is_(None))
        .order_by(Invite.created_at.desc())
        .limit(80)
        .all()
    )
    house_ids = {i.household_id for i in family_keys if i.household_id}
    houses = {
        h.id: h
        for h in Household.query.filter(Household.id.in_(house_ids)).all()
    } if house_ids else {}
    return render_template(
        "platform/access.html",
        owner=current_owner(),
        issued_key=pop_issued_key(),
        service_keys=ServicePass.query.order_by(ServicePass.created_at.desc()).limit(80).all(),
        family_keys=family_keys,
        houses=houses,
        trusted=TrustedEmail.query.order_by(TrustedEmail.created_at.desc()).all(),
        owner_keys=PlatformInvite.query.order_by(PlatformInvite.created_at.desc()).limit(40).all(),
    )


@platform_bp.route("/households/<int:hid>/suspend", methods=["POST"])
@require_owner
def suspend_household(hid):
    h = Household.query.get_or_404(hid)
    h.is_active = False
    db.session.commit()
    audit(
        "household.suspend",
        owner_id=_owner_id(),
        household_id=h.id,
        ip=_ip(),
        detail={"name": h.name},
    )
    flash(f"{h.name} is paused. Leaders can no longer sign in.", "warning")
    return redirect(url_for("platform.households"))


@platform_bp.route("/households/<int:hid>/resume", methods=["POST"])
@require_owner
def resume_household(hid):
    h = Household.query.get_or_404(hid)
    h.is_active = True
    db.session.commit()
    audit(
        "household.resume",
        owner_id=_owner_id(),
        household_id=h.id,
        ip=_ip(),
        detail={"name": h.name},
    )
    flash(f"{h.name} is active again.", "success")
    return redirect(url_for("platform.households"))


@platform_bp.route("/households/<int:hid>/delete", methods=["POST"])
@require_owner
def delete_household(hid):
    from app.utils.household_delete import confirm_matches, confirm_phrase, delete_household as wipe

    h = Household.query.get_or_404(hid)
    typed = request.form.get("confirm") or ""
    if not confirm_matches(h, typed):
        flash(f'Type "{confirm_phrase(h)}" to delete this household.', "danger")
        return redirect(url_for("platform.households"))
    name = wipe(h)
    audit(
        "household.delete",
        owner_id=_owner_id(),
        household_id=hid,
        ip=_ip(),
        detail={"name": name},
    )
    flash(f"{name} is gone. That cannot be undone.", "info")
    return redirect(url_for("platform.households"))


@platform_bp.route("/email", methods=["GET", "POST"])
@require_owner
def email_settings():
    if request.method == "POST":
        mode = (request.form.get("mail_mode") or "console").strip().lower()
        if mode not in ("console", "smtp"):
            mode = "console"
        enc = (request.form.get("smtp_encryption") or "tls").strip().lower()
        if enc not in ("tls", "ssl", "none"):
            enc = "tls"
        set_setting("mail_mode", mode)
        set_setting("mail_from_name", (request.form.get("mail_from_name") or "").strip())
        set_setting("mail_from_email", (request.form.get("mail_from_email") or "").strip())
        set_setting("mail_reply_to", (request.form.get("mail_reply_to") or "").strip())
        set_setting("smtp_host", (request.form.get("smtp_host") or "").strip())
        set_setting("smtp_port", (request.form.get("smtp_port") or "587").strip())
        set_setting("smtp_encryption", enc)
        set_setting("smtp_username", (request.form.get("smtp_username") or "").strip())
        new_pass = request.form.get("smtp_password") or ""
        if new_pass.strip():
            set_setting("smtp_password", new_pass, secret=True)
        audit("email.save", owner_id=_owner_id(), ip=_ip(), detail={"mode": mode})
        flash("Email settings saved.", "success")
        return redirect(url_for("platform.email_settings"))
    cfg = mail_config()
    cfg["smtp_password_hint"] = mask_secret(cfg.get("smtp_password") or "")
    cfg.pop("smtp_password", None)
    return render_template(
        "platform/email.html",
        owner=current_owner(),
        mail=cfg,
    )


@platform_bp.route("/email/test", methods=["POST"])
@require_owner
def email_test():
    owner = current_owner()
    to_addr = (request.form.get("to") or "").strip() or (owner.email if owner else "")
    ok, msg = send_mail(
        to_addr,
        "Family OS platform test",
        "This is a test from the Family OS owner console. If you can read it, outbound mail works.",
    )
    audit(
        "email.test",
        owner_id=_owner_id(),
        ip=_ip(),
        detail={"ok": ok, "to": to_addr},
    )
    flash(msg, "success" if ok else "danger")
    return redirect(url_for("platform.email_settings"))


@platform_bp.route("/ai", methods=["GET", "POST"])
@require_owner
def ai_settings():
    if request.method == "POST":
        provider = normalize_provider(request.form.get("ai_provider"))
        model = (request.form.get("ai_model") or "").strip() or DEFAULT_MODEL
        base = (request.form.get("ai_base_url") or "").strip()
        set_setting("ai_provider", provider)
        set_setting("ai_model", model)
        set_setting("ai_base_url", base)
        new_key = (request.form.get("ai_api_key") or "").strip()
        if new_key:
            set_setting("ai_api_key", new_key, secret=True)
        audit("ai.save", owner_id=_owner_id(), ip=_ip(), detail={"provider": provider, "model": model})
        flash("Owner-console AI saved. Households do not use this key.", "success")
        return redirect(url_for("platform.ai_settings"))
    return render_template(
        "platform/ai.html",
        owner=current_owner(),
        ai=public_ai_config(),
    )


@platform_bp.route("/ai/test", methods=["POST"])
@require_owner
def ai_test():
    ok, msg = ping_ai()
    audit("ai.test", owner_id=_owner_id(), ip=_ip(), detail={"ok": ok})
    flash(msg, "success" if ok else "danger")
    return redirect(url_for("platform.ai_settings"))


@platform_bp.route("/password", methods=["POST"])
@require_owner
def change_password():
    owner = current_owner()
    current = request.form.get("current_password") or ""
    new = request.form.get("new_password") or ""
    confirm = request.form.get("confirm_password") or ""
    if not owner or not owner.check_password(current):
        flash("Current password is wrong.", "danger")
        return redirect(url_for("platform.home"))
    if len(new) < 8:
        flash("New password needs at least 8 characters.", "danger")
        return redirect(url_for("platform.home"))
    if new != confirm:
        flash("New passwords do not match.", "danger")
        return redirect(url_for("platform.home"))
    owner.set_password(new)
    db.session.commit()
    audit("owner.password", owner_id=owner.id, ip=_ip())
    flash("Platform password updated.", "success")
    return redirect(url_for("platform.home"))


@platform_bp.route("/audit")
@require_owner
def audit_log():
    rows = PlatformAudit.query.order_by(PlatformAudit.created_at.desc()).limit(200).all()
    return render_template(
        "platform/audit.html",
        owner=current_owner(),
        rows=rows,
    )
