from datetime import datetime

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy.orm import selectinload

from app.builddb.builddb import db
from app.builddb.table_users import User
from app.builddb.table_vault_entries import VaultEntry
from app.builddb.table_vault_grants import VaultGrant
from app.utils.household import household_id, scoped
from app.utils.password_vault import (
    DURATIONS,
    REAUTH_SECONDS,
    SHARE_MODES,
    can_manage_entry,
    can_use_vault,
    can_view_entry,
    confirm_app_login,
    duration_key_for,
    grant_label,
    href_for,
    is_child,
    lock_reauth,
    mark_reauth,
    open_fields,
    touch_reauth,
    parse_duration,
    reauth_ok,
    reauth_remaining,
    seal_fields,
    share_label,
)

vault_bp = Blueprint("vault", __name__, url_prefix="/vault")

_LIMITS = {
    "title": 200,
    "login": 300,
    "secret": 500,
    "url": 500,
    "purpose": 500,
    "details": 4000,
}


def _adults(hid: int):
    return (
        User.query.filter_by(household_id=hid, is_active=True)
        .filter(User.role != "child")
        .order_by(User.name.asc(), User.username.asc())
        .all()
    )


def _people_map(hid: int) -> dict:
    return {u.id: u for u in User.query.filter_by(household_id=hid).all()}


def _nostore(resp):
    resp.headers["Cache-Control"] = "private, no-store, no-cache, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@vault_bp.after_request
def _vault_headers(response):
    return _nostore(response)


@vault_bp.before_request
def _slide_open_vault():
    if request.endpoint in ("vault.lock", "vault.unlock"):
        return None
    if reauth_ok():
        touch_reauth()
    return None


def _guard():
    if is_child() or not can_use_vault():
        abort(403)


def _form_fields():
    out = {}
    for key, cap in _LIMITS.items():
        out[key] = (request.form.get(key) or "").strip()[:cap]
    return out


def _share_from_form() -> str:
    mode = (request.form.get("share_mode") or "personal").strip().lower()
    if mode not in SHARE_MODES:
        mode = "personal"
    return mode


def _replace_grants(entry, hid: int, mode: str) -> None:
    existing = {int(g.user_id): g for g in (entry.grants or [])}
    VaultGrant.query.filter_by(entry_id=entry.id, household_id=hid).delete(
        synchronize_session=False
    )
    if mode != "selected":
        return
    adults = {u.id: u for u in _adults(hid)}
    seen = set()
    for raw in request.form.getlist("person"):
        if not str(raw).isdigit():
            continue
        uid = int(raw)
        if uid not in adults or uid == current_user.id or uid in seen:
            continue
        seen.add(uid)
        dur = (request.form.get(f"for_{uid}") or "forever").strip().lower()
        old = existing.get(uid)
        if old is not None and duration_key_for(old.expires_at) == dur:
            expires = old.expires_at
        else:
            expires = parse_duration(dur)
        db.session.add(
            VaultGrant(
                household_id=hid,
                entry_id=entry.id,
                user_id=uid,
                granted_by=current_user.id,
                expires_at=expires,
            )
        )


def _visible_query(hid: int, uid: int):
    return (
        scoped(VaultEntry)
        .options(selectinload(VaultEntry.grants))
        .order_by(VaultEntry.updated_at.desc())
    )


def _filter_visible(rows, user):
    return [row for row in rows if can_view_entry(row, user)]


def _card(row, people: dict, opened: bool) -> dict:
    fields = open_fields(row) if opened else {k: "" for k in ("title", "login", "secret", "url", "purpose", "details")}
    grants = [g for g in (row.grants or [])]
    grant_ids = {int(g.user_id): g for g in grants}
    return {
        "row": row,
        "fields": fields,
        "href": href_for(fields.get("url") or ""),
        "share": share_label(row.share_mode),
        "owner": people.get(row.created_by),
        "grants": [grant_label(g, people) for g in grants],
        "grant_rows": grants,
        "grant_ids": grant_ids,
        "grant_durs": {uid: duration_key_for(g.expires_at) for uid, g in grant_ids.items()},
        "can_manage": can_manage_entry(row, current_user),
        "mine": int(row.created_by or 0) == int(current_user.id),
    }


def _render_index(*, draft=None):
    hid = household_id()
    opened = reauth_ok()
    q = (request.args.get("q") or "").strip()[:80]
    scope = (request.args.get("scope") or "all").strip().lower()
    cards = []
    if opened:
        rows = _filter_visible(_visible_query(hid, current_user.id).all(), current_user)
        people = _people_map(hid)
        if scope == "house":
            rows = [r for r in rows if r.share_mode == "household"]
        elif scope == "mine":
            rows = [r for r in rows if int(r.created_by or 0) == int(current_user.id)]
        elif scope == "shared":
            rows = [r for r in rows if r.share_mode == "selected"]
        needle = q.lower()
        for row in rows:
            card = _card(row, people, True)
            if needle:
                blob = " ".join(
                    [
                        card["fields"].get("title") or "",
                        card["fields"].get("login") or "",
                        card["fields"].get("url") or "",
                        card["fields"].get("purpose") or "",
                        card["fields"].get("details") or "",
                    ]
                ).lower()
                if needle not in blob:
                    continue
            cards.append(card)
    return render_template(
        "vault.html",
        opened=opened,
        cards=cards,
        q=q,
        scope=scope,
        adults=_adults(hid),
        durations=DURATIONS,
        remaining=reauth_remaining() if opened else 0,
        remaining_min=max(1, (reauth_remaining() + 59) // 60) if opened else 0,
        reauth_minutes=REAUTH_SECONDS // 60,
        vault_keep=opened,
        draft=draft or {},
    )


@vault_bp.route("/")
@login_required
def index():
    _guard()
    return _render_index()


@vault_bp.route("/unlock", methods=["POST"])
@login_required
def unlock():
    _guard()
    username = request.form.get("username") or ""
    password = request.form.get("password") or ""
    if not confirm_app_login(
        current_user,
        username=username,
        password=password,
    ):
        flash("That is not this login. Use the same username and password you sign in with.", "danger")
        return redirect(url_for("vault.index"))
    mark_reauth()
    flash("Vault open. It stays open while you use it.", "success")
    return redirect(url_for("vault.index"))


@vault_bp.route("/stay", methods=["POST"])
@login_required
def stay():
    _guard()
    if not reauth_ok():
        return {"ok": False}, 401
    touch_reauth()
    return {"ok": True, "left": reauth_remaining()}


@vault_bp.route("/lock", methods=["POST"])
@login_required
def lock():
    _guard()
    lock_reauth()
    flash("Vault locked.", "info")
    return redirect(url_for("vault.index"))


@vault_bp.route("/add", methods=["POST"])
@login_required
def add():
    _guard()
    fields = _form_fields()
    if not fields["title"]:
        flash("Give it a title.", "danger")
        return _render_index(draft=fields) if reauth_ok() else redirect(url_for("vault.index"))
    hid = household_id()
    try:
        sealed = seal_fields(fields, hid)
        row = VaultEntry(
            household_id=hid,
            created_by=current_user.id,
            share_mode="personal",
            **sealed,
        )
        db.session.add(row)
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        flash("Could not save that login. Try Save again.", "danger")
        return _render_index(draft=fields) if reauth_ok() else redirect(url_for("vault.index"))
    flash("Saved. Username, password, and details are on the card. Share it if you want.", "success")
    return redirect(url_for("vault.index", _anchor=f"login-{row.id}"))


@vault_bp.route("/<int:entry_id>/edit", methods=["POST"])
@login_required
def edit(entry_id):
    _guard()
    if not reauth_ok():
        flash("Sign in again to change a login.", "warning")
        return redirect(url_for("vault.index"))
    hid = household_id()
    row = scoped(VaultEntry).options(selectinload(VaultEntry.grants)).filter_by(id=entry_id).first_or_404()
    if not can_manage_entry(row, current_user):
        abort(403)
    if not can_view_entry(row, current_user):
        abort(403)
    fields = _form_fields()
    if not fields["title"]:
        flash("Give it a title.", "danger")
        return redirect(url_for("vault.index", _anchor=f"login-{entry_id}"))
    sealed = seal_fields(fields, hid)
    for key, val in sealed.items():
        setattr(row, key, val)
    row.updated_at = datetime.utcnow()
    db.session.commit()
    flash("Login updated.", "success")
    return redirect(url_for("vault.index", _anchor=f"login-{entry_id}"))


@vault_bp.route("/<int:entry_id>/share", methods=["POST"])
@login_required
def share(entry_id):
    _guard()
    if not reauth_ok():
        flash("Sign in again to change who sees this.", "warning")
        return redirect(url_for("vault.index"))
    hid = household_id()
    row = scoped(VaultEntry).options(selectinload(VaultEntry.grants)).filter_by(id=entry_id).first_or_404()
    if not can_manage_entry(row, current_user):
        abort(403)
    mode = _share_from_form()
    row.share_mode = mode
    row.updated_at = datetime.utcnow()
    _replace_grants(row, hid, mode)
    db.session.commit()
    flash("Who can see this is updated. Change it anytime.", "success")
    return redirect(url_for("vault.index", _anchor=f"login-{entry_id}"))


@vault_bp.route("/<int:entry_id>")
@login_required
def detail(entry_id):
    _guard()
    if not reauth_ok():
        flash("Sign in again to open the vault.", "warning")
        return redirect(url_for("vault.index"))
    row = scoped(VaultEntry).filter_by(id=entry_id).first_or_404()
    if not can_view_entry(row, current_user) and not can_manage_entry(row, current_user):
        abort(403)
    return redirect(url_for("vault.index", _anchor=f"login-{entry_id}"))


@vault_bp.route("/<int:entry_id>/delete", methods=["POST"])
@login_required
def delete(entry_id):
    _guard()
    if not reauth_ok():
        flash("Sign in again to remove a login.", "warning")
        return redirect(url_for("vault.index"))
    row = scoped(VaultEntry).filter_by(id=entry_id).first_or_404()
    if not can_manage_entry(row, current_user):
        abort(403)
    db.session.delete(row)
    db.session.commit()
    flash("Removed from the vault.", "info")
    return redirect(url_for("vault.index"))
