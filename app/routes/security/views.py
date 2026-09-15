"""Family OS owner security console — attacks, bans, devices, events."""
from functools import wraps

from flask import flash, redirect, render_template, request, url_for, abort, jsonify

from . import security_bp
from .utils import (
    can_access_security_console,
    ban_ip_console,
    unban_ip_console,
    trust_ip_console,
    ban_device_console,
    unban_device_console,
    csrf_token,
    csrf_ok,
    clear_account_login_lock,
)
from . import queries as q


def security_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        from app.utils.platform_auth import is_owner

        if not is_owner():
            return redirect(url_for("platform.login", next=request.path))
        if not can_access_security_console():
            abort(403)
        return f(*args, **kwargs)

    return wrapped


def _base_ctx(**extra):
    from app.utils.platform_auth import current_owner

    ctx = {
        "owner": current_owner(),
        "csrf_token": csrf_token(),
        "can_manage_access": True,
    }
    ctx.update(extra)
    return ctx


def _audit(action, detail=None):
    try:
        from app.utils.platform_settings import audit
        from app.utils.platform_auth import current_owner

        row = current_owner()
        audit(action, owner_id=None if row is None else row.id, detail=detail, ip=request.remote_addr)
    except Exception:
        pass


@security_bp.route("/csrf-token")
@security_required
def csrf_token_refresh():
    return jsonify({"ok": True, "csrf_token": csrf_token()})


@security_bp.route("/")
@security_required
def dashboard():
    try:
        from poweredbytop.reputation.scorer import bootstrap_reputation_from_history

        bootstrap_reputation_from_history(force=False, limit=50)
    except Exception:
        pass
    stats = q.summary_stats()
    recent_events, _ = q.list_security_events(limit=12, offset=0)
    bans = q.list_reputation_rows(filter_mode="bans", limit=12)
    locks = q.list_account_login_locks()
    attack_stats = q.list_attack_stats()[:15]
    device_bans = q.list_device_bans(limit=12)
    return render_template(
        "security/dashboard.html",
        stats=stats,
        recent_events=recent_events,
        bans=bans,
        locks=locks,
        attack_stats=attack_stats,
        device_bans=device_bans,
        page_title="Security",
        **_base_ctx(),
    )


@security_bp.route("/events")
@security_required
def events():
    search = request.args.get("search", "").strip()
    ip = (request.args.get("ip") or "").strip()
    device_fp = (request.args.get("device_fp") or request.args.get("fp") or "").strip()
    event_type = request.args.get("type", "").strip()
    honeypot_only = request.args.get("honeypot", "").strip() in ("1", "true", "yes", "on")
    page = max(1, int(request.args.get("page", 1) or 1))
    page_size = 50
    rows, total = q.list_security_events(
        search=search,
        event_type="" if honeypot_only else event_type,
        honeypot_only=honeypot_only,
        ip=ip,
        device_fp=device_fp,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    total_pages = max(1, (total + page_size - 1) // page_size) if total else 1
    return render_template(
        "security/events.html",
        events=rows,
        total=total,
        page=page,
        total_pages=total_pages,
        search=search,
        filter_ip=ip,
        filter_device_fp=device_fp,
        event_type=event_type,
        honeypot_only=honeypot_only,
        event_types=q.list_event_types(),
        page_title="Security events",
        **_base_ctx(),
    )


@security_bp.route("/attacks")
@security_required
def attacks():
    return render_template(
        "security/attacks.html",
        attack_stats=q.list_attack_stats(),
        page_title="Attack totals",
        **_base_ctx(),
    )


@security_bp.route("/bans", methods=["GET", "POST"])
@security_required
def bans():
    if request.method == "POST":
        if not csrf_ok():
            flash("Security check failed. Reload and try again.", "danger")
            return redirect(url_for("security.bans"))
        action = (request.form.get("action") or "").strip()
        ip = (request.form.get("ip") or "").strip()
        if action == "recalc_top":
            try:
                from poweredbytop.reputation.scorer import reconcile_top_offenders

                results = reconcile_top_offenders(limit=40)
                flash(f"Recalculated {len(results)} top offender IP(s).", "success")
            except Exception as exc:
                flash(f"Could not recalculate: {exc}", "danger")
            return redirect(url_for("security.bans", filter="low"))
        if not ip:
            flash("IP is required.", "danger")
            return redirect(url_for("security.bans"))
        if action == "unban":
            flash(f"Removed ban for {ip}." if unban_ip_console(ip) else f"No row for {ip}.", "success")
            _audit("security.unban_ip", {"ip": ip})
        elif action == "trust":
            flash(f"Trusted {ip}." if trust_ip_console(ip) else f"Could not trust {ip}.", "success")
            _audit("security.trust_ip", {"ip": ip})
        elif action == "temp_ban":
            hours = int(request.form.get("hours") or 1)
            reason = (request.form.get("reason") or "Manual temp ban").strip()
            ok = ban_ip_console(ip, reason, permanent=False, hours=hours)
            flash(f"Temp-banned {ip} for {hours}h." if ok else f"Could not ban {ip}.", "success" if ok else "danger")
            _audit("security.temp_ban", {"ip": ip, "hours": hours})
        elif action == "perm_ban":
            reason = (request.form.get("reason") or "Manual permanent ban").strip()
            ok = ban_ip_console(ip, reason, permanent=True)
            flash(f"Permanently banned {ip}." if ok else f"Could not ban {ip}.", "success" if ok else "danger")
            _audit("security.perm_ban", {"ip": ip})
        return redirect(url_for("security.bans"))
    mode = (request.args.get("filter") or "bans").strip()
    if mode not in ("bans", "low", "all"):
        mode = "bans"
    rows = q.list_reputation_rows(filter_mode=mode, search=request.args.get("search") or "", limit=150)
    return render_template(
        "security/bans.html",
        rows=rows,
        filter_mode=mode,
        search=request.args.get("search") or "",
        page_title="Bans",
        **_base_ctx(),
    )


@security_bp.route("/devices", methods=["GET", "POST"])
@security_required
def devices():
    if request.method == "POST":
        if not csrf_ok():
            flash("Security check failed. Reload and try again.", "danger")
            return redirect(url_for("security.devices"))
        action = (request.form.get("action") or "").strip()
        fp = (request.form.get("device_fp") or "").strip()
        if action == "unban_device" and fp:
            flash("Device unbanned." if unban_device_console(fp) else "Could not unban.", "success")
            _audit("security.unban_device", {"fp": fp[:16]})
        elif action == "ban_device" and fp:
            hours = int(request.form.get("hours") or 6)
            reason = (request.form.get("reason") or "Manual device ban").strip()
            perm = (request.form.get("permanent") or "") == "1"
            ok = ban_device_console(fp, reason, hours=hours, permanent=perm)
            flash("Device banned." if ok else "Could not ban device.", "success" if ok else "danger")
            _audit("security.ban_device", {"fp": fp[:16]})
        return redirect(url_for("security.devices"))
    search = (request.args.get("search") or "").strip()
    try:
        rows = q.list_device_prints(search=search, limit=80)
    except Exception:
        rows = []
    return render_template(
        "security/devices.html",
        rows=rows,
        active_bans=q.list_device_bans(limit=50),
        search=search,
        page_title="Devices",
        **_base_ctx(),
    )


@security_bp.route("/locks", methods=["POST"])
@security_required
def unlock_account():
    if not csrf_ok():
        flash("Security check failed.", "danger")
        return redirect(url_for("security.dashboard"))
    try:
        uid = int(request.form.get("user_id") or 0)
    except Exception:
        uid = 0
    if uid and clear_account_login_lock(uid):
        flash("Login lock cleared.", "success")
        _audit("security.unlock", {"user_id": uid})
    else:
        flash("Could not unlock that account.", "danger")
    nxt = request.form.get("next") or ""
    if nxt.startswith("/security"):
        return redirect(nxt)
    return redirect(url_for("security.dashboard"))


@security_bp.route("/locks")
@security_required
def account_locks():
    return render_template(
        "security/account_locks.html",
        locks=q.list_account_login_locks(),
        page_title="Login locks",
        **_base_ctx(),
    )


@security_bp.route("/devices/trail")
@security_required
def device_trail():
    fp = (request.args.get("device_fp") or request.args.get("fp") or "").strip()
    if not fp:
        flash("Pick a device from the list first.", "warning")
        return redirect(url_for("security.devices"))
    try:
        limit = int(request.args.get("limit") or 200)
    except Exception:
        limit = 200
    trail = q.get_device_activity_trail(fp, limit=max(20, min(limit, 500)))
    return render_template(
        "security/device_trail.html",
        trail=trail,
        device_fp=fp,
        page_title="Device trail",
        **_base_ctx(),
    )


@security_bp.route("/audit")
@security_required
def audit():
    search = (request.args.get("search") or "").strip()
    action = (request.args.get("action") or "").strip()
    ip = (request.args.get("ip") or "").strip()
    try:
        days = int(request.args.get("days") or 30)
    except Exception:
        days = 30
    page = max(1, int(request.args.get("page") or 1))
    page_size = 50
    rows, total = q.list_audit_logs(
        search=search,
        action=action,
        ip=ip,
        days=days if days > 0 else None,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    total_pages = max(1, (total + page_size - 1) // page_size) if total else 1
    return render_template(
        "security/audit.html",
        logs=rows,
        total=total,
        page=page,
        total_pages=total_pages,
        search=search,
        action=action,
        ip=ip,
        days=days,
        actions=q.list_audit_actions(),
        action_counts=q.audit_action_counts(days=days or 30, limit=20),
        page_title="Owner audit",
        **_base_ctx(),
    )


@security_bp.route("/investigate")
@security_required
def investigate():
    device_fp = (request.args.get("device_fp") or request.args.get("fp") or "").strip()
    ip = (request.args.get("ip") or "").strip()
    user_q = (request.args.get("user_q") or "").strip()
    needle = (request.args.get("q") or request.args.get("search") or "").strip()
    match = (request.args.get("match") or "all").strip().lower()
    if match not in ("all", "any"):
        match = "all"
    user_id = None
    try:
        user_id = int(request.args.get("user_id") or 0) or None
    except Exception:
        user_id = None
    if not user_id and user_q:
        if user_q.isdigit():
            user_id = int(user_q)
        else:
            hits = q.search_users(user_q, limit=1)
            if hits:
                user_id = hits[0]["id"]
    bundle = q.investigate(
        user_id=user_id,
        device_fp=device_fp,
        ip=ip,
        q=needle,
        match=match,
        limit=200,
    )
    return render_template(
        "security/investigate.html",
        inv=bundle,
        user_q=user_q,
        page_title="Investigate",
        **_base_ctx(),
    )


@security_bp.route("/users")
@security_required
def users_search():
    term = (request.args.get("q") or "").strip()
    results = q.search_users(term, limit=40) if term else []
    return render_template(
        "security/users_search.html",
        term=term,
        results=results,
        page_title="People",
        **_base_ctx(),
    )


@security_bp.route("/users/<int:user_id>")
@security_required
def user_profile(user_id: int):
    profile = q.get_user_security_profile(user_id)
    if not profile:
        flash("Person not found.", "danger")
        return redirect(url_for("security.users_search"))
    return render_template(
        "security/user_profile.html",
        profile=profile,
        page_title=f"Person · {profile['user']['username']}",
        **_base_ctx(),
    )


@security_bp.route("/ip-pairs")
@security_required
def ip_pairs():
    ip = (request.args.get("ip") or "").strip()
    user_q = (request.args.get("user_q") or "").strip()
    users_for_ip = q.list_users_for_ip(ip, limit=80) if ip else []
    ips_for_user = []
    selected_user = None
    if user_q:
        matches = q.search_users(user_q, limit=1)
        if user_q.isdigit():
            selected_user = int(user_q)
        elif matches:
            selected_user = matches[0]["id"]
        if selected_user:
            ips_for_user = q.list_ips_for_user(selected_user, limit=80)
    return render_template(
        "security/ip_pairs.html",
        ip=ip,
        user_q=user_q,
        users_for_ip=users_for_ip,
        ips_for_user=ips_for_user,
        selected_user=selected_user,
        recent=q.list_recent_ip_pairs(limit=80),
        page_title="User ↔ IP",
        **_base_ctx(),
    )
