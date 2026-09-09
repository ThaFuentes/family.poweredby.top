"""Owner / platform console. You are not a household user."""
from __future__ import annotations

import os

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
from app.utils.ai import public_ai_config, ping_ai, normalize_provider
from app.utils.leaders import fleet_cards
from app.utils.mail import mail_config, send_mail
from app.utils.platform_auth import (
    bootstrap_token_ok,
    bootstrap_token_required,
    current_owner,
    find_owner,
    is_owner,
    login_owner,
    logout_owner,
    mark_login_failure,
    mark_login_success,
    needs_setup,
    owner_is_locked,
    require_owner,
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


@platform_bp.route("/login", methods=["GET", "POST"])
def login():
    if is_owner():
        return redirect(url_for("platform.home"))
    setup = needs_setup()
    token_needed = setup and bootstrap_token_required()
    if request.method != "POST":
        return render_template(
            "platform/login.html",
            setup=setup,
            token_needed=token_needed,
            error=None,
        )

    if setup:
        username = (request.form.get("username") or "").strip()
        name = (request.form.get("name") or "").strip() or username
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""
        token = request.form.get("bootstrap_token") or ""
        err = None
        if len(username) < 2:
            err = "Pick a username."
        elif "@" not in email:
            err = "Platform owner needs an email."
        elif len(password) < 8:
            err = "Password needs at least 8 characters."
        elif password != confirm:
            err = "Passwords do not match."
        elif not bootstrap_token_ok(token):
            if (os.getenv("PLATFORM_BOOTSTRAP_TOKEN") or "").strip():
                err = "Bootstrap token does not match."
            else:
                err = "Set PLATFORM_BOOTSTRAP_TOKEN in .env, then reload. First owner is locked until then."
        if err:
            return render_template(
                "platform/login.html",
                setup=True,
                token_needed=token_needed,
                error=err,
            ), 400
        owner = PlatformOwner(username=username, name=name, email=email, is_active=True)
        owner.set_password(password)
        db.session.add(owner)
        db.session.commit()
        login_owner(owner)
        audit("owner.bootstrap", owner_id=owner.id, ip=_ip(), detail={"username": username})
        flash("Platform owner created. This login is not a household account.", "success")
        return redirect(_safe_next())

    ident = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    owner = find_owner(ident)
    if owner and owner_is_locked(owner):
        return render_template(
            "platform/login.html",
            setup=False,
            token_needed=False,
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
        token_needed=False,
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
    from app.utils.access import add_trusted_email, mint_service_pass, revoke_service_pass

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
            flash(f"Service key {row.code} — gets someone onto Family OS, not into a household.", "success")
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
        return redirect(url_for("platform.access"))
    return render_template(
        "platform/access.html",
        owner=current_owner(),
        service_keys=ServicePass.query.order_by(ServicePass.created_at.desc()).limit(80).all(),
        trusted=TrustedEmail.query.order_by(TrustedEmail.created_at.desc()).all(),
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
        model = (request.form.get("ai_model") or "").strip() or "grok-4.6"
        base = (request.form.get("ai_base_url") or "").strip()
        set_setting("ai_provider", provider)
        set_setting("ai_model", model)
        set_setting("ai_base_url", base)
        new_key = (request.form.get("ai_api_key") or "").strip()
        if new_key:
            set_setting("ai_api_key", new_key, secret=True)
        audit("ai.save", owner_id=_owner_id(), ip=_ip(), detail={"provider": provider, "model": model})
        flash("Fallback AI saved. Households still bring their own keys first.", "success")
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
