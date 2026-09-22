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
    KIND_ADD,
    KIND_CHOICE,
    KIND_LABELS,
    KIND_ONE,
    KINDS,
    REAUTH_SECONDS,
    SECRET_FIELDS,
    SHARE_MODES,
    TWO_FACTOR,
    can_manage_entry,
    can_use_vault,
    can_view_entry,
    confirm_app_login,
    ended_grants,
    grant_is_live,
    grant_label,
    grant_view,
    household_opened,
    href_for,
    is_child,
    kind_label,
    kind_of,
    kind_one,
    live_grants,
    log_vault_access,
    open_fields,
    parse_duration,
    recent_access,
    site_label,
    lock_reauth,
    mark_reauth,
    touch_reauth,
    reauth_ok,
    reauth_remaining,
    seal_fields,
    share_label,
    two_factor_label,
)

vault_bp = Blueprint("vault", __name__, url_prefix="/vault")

_LIMITS = {
    "title": 200,
    "login": 300,
    "secret": 500,
    "url": 500,
    "purpose": 500,
    "details": 4000,
    "phone": 80,
    "phone_alt": 80,
    "account_no": 200,
    "two_factor": 20,
    "two_factor_detail": 1000,
    "call_info": 4000,
}
_TWO_FACTOR_KEYS = {key for key, _lab in TWO_FACTOR}


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
    if out.get("two_factor") not in _TWO_FACTOR_KEYS:
        out["two_factor"] = ""
    return out


def _kind_from_request(default: str = "password") -> str:
    raw = (request.form.get("kind") or request.args.get("kind") or default or "password").strip().lower()
    return raw if raw in KINDS else "password"


def _share_from_form() -> str:
    mode = (request.form.get("share_mode") or "personal").strip().lower()
    if mode not in SHARE_MODES:
        mode = "personal"
    return mode


def _person_id(raw) -> int | None:
    if not str(raw or "").isdigit():
        return None
    uid = int(raw)
    return uid if uid > 0 else None


def _revoke_live(entry, hid: int, uid: int | None = None) -> int:
    now = datetime.utcnow()
    n = 0
    for g in entry.grants or []:
        if uid is not None and int(g.user_id) != int(uid):
            continue
        if not grant_is_live(g, now):
            continue
        g.revoked_at = now
        n += 1
        try:
            from types import SimpleNamespace

            log_vault_access(entry, SimpleNamespace(id=g.user_id), "revoked", grant=g)
        except Exception:
            pass
    return n


def _give_access(entry, hid: int, uid: int, duration: str) -> VaultGrant:
    now = datetime.utcnow()
    adults = {u.id: u for u in _adults(hid)}
    if uid not in adults or uid == current_user.id:
        raise ValueError("That person cannot be given this.")
    live = None
    for g in entry.grants or []:
        if int(g.user_id) != uid:
            continue
        if grant_is_live(g, now):
            live = g
            break
    expires = parse_duration(duration)
    key = (duration or "forever").strip().lower()
    if key not in dict(DURATIONS):
        key = "forever"
        expires = None
    person = adults.get(uid)
    if live is not None:
        live.expires_at = expires
        live.duration_key = key
        live.granted_by = current_user.id
        try:
            log_vault_access(entry, person or current_user, "extended", grant=live)
        except Exception:
            pass
        return live
    row = VaultGrant(
        household_id=hid,
        entry_id=entry.id,
        user_id=uid,
        granted_by=current_user.id,
        duration_key=key,
        expires_at=expires,
    )
    db.session.add(row)
    db.session.flush()
    try:
        log_vault_access(entry, person or current_user, "granted", grant=row)
    except Exception:
        pass
    return row


def _filter_visible(rows, user):
    return [row for row in rows if can_view_entry(row, user)]


def _card(row, people: dict, opened: bool, adults=None) -> dict:
    fields = open_fields(row) if opened else {k: "" for k in SECRET_FIELDS}
    grants = [g for g in (row.grants or [])]
    live = live_grants(grants)
    ended = ended_grants(grants)
    kind = kind_of(row)
    live_ids = {int(g.user_id) for g in live}
    give_people = [p for p in (adults or []) if p.id != current_user.id and p.id not in live_ids]
    return {
        "row": row,
        "fields": fields,
        "kind": kind,
        "kind_label": kind_label(kind),
        "kind_one": kind_one(kind),
        "two_factor": two_factor_label(fields.get("two_factor") or ""),
        "href": href_for(fields.get("url") or ""),
        "tel": "".join(ch for ch in (fields.get("phone") or "") if ch.isdigit() or ch in "+"),
        "site": site_label(fields.get("url") or ""),
        "share": share_label(row.share_mode),
        "owner": people.get(row.created_by),
        "grants": [grant_label(g, people) for g in live],
        "live_grants": [grant_view(g, people) for g in live],
        "ended_grants": [grant_view(g, people) for g in ended],
        "give_people": give_people,
        "opened_by": household_opened(row, adults or [], people) if row.share_mode == "household" else [],
        "access_log": recent_access(row, people) if can_manage_entry(row, current_user) else [],
        "can_manage": can_manage_entry(row, current_user),
        "mine": int(row.created_by or 0) == int(current_user.id),
    }


def _wants_sheet() -> bool:
    nxt = (request.form.get("next") or request.args.get("next") or "").strip().lower()
    return nxt == "sheet"


def _entry_query():
    return scoped(VaultEntry).options(
        selectinload(VaultEntry.grants),
        selectinload(VaultEntry.access),
    )


def _render_new(*, draft=None, ping_saved=False, kind=None):
    chosen = kind_of(kind or (draft or {}).get("kind") or _kind_from_request())
    return render_template(
        "vault_new.html",
        draft=draft or {},
        ping_saved=ping_saved,
        kind=chosen,
        kinds=KINDS,
        kind_labels=KIND_LABELS,
        kind_choices=KIND_CHOICE,
        kind_one=kind_one(chosen),
        two_factor=TWO_FACTOR,
    )


def _render_detail(entry_id, *, ping_saved=False):
    hid = household_id()
    row = _entry_query().filter_by(id=entry_id).first_or_404()
    if not can_view_entry(row, current_user) and not can_manage_entry(row, current_user):
        abort(403)
    people = _people_map(hid)
    adults = _adults(hid)
    can_read = can_view_entry(row, current_user)
    if can_read and int(row.created_by or 0) != int(current_user.id):
        try:
            log_vault_access(row, current_user, "view")
            db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            row = _entry_query().filter_by(id=entry_id).first_or_404()
    return render_template(
        "vault_detail.html",
        card=_card(row, people, can_read, adults),
        adults=adults,
        durations=DURATIONS,
        kinds=KINDS,
        kind_labels=KIND_LABELS,
        kind_choices=KIND_CHOICE,
        two_factor=TWO_FACTOR,
        can_read=can_read,
        ping_saved=ping_saved,
    )


def _render_index(*, draft=None):
    hid = household_id()
    opened = reauth_ok()
    q = (request.args.get("q") or "").strip()[:80]
    scope = (request.args.get("scope") or "all").strip().lower()
    kind = (request.args.get("kind") or "").strip().lower()
    if kind and kind not in KINDS:
        kind = ""
    cards = []
    adults = _adults(hid)
    if opened:
        rows = _filter_visible(_entry_query().order_by(VaultEntry.updated_at.desc()).all(), current_user)
        people = _people_map(hid)
        if kind:
            rows = [r for r in rows if kind_of(r) == kind]
        if scope == "house":
            rows = [r for r in rows if r.share_mode == "household"]
        elif scope == "mine":
            rows = [r for r in rows if int(r.created_by or 0) == int(current_user.id)]
        elif scope == "shared":
            rows = [r for r in rows if r.share_mode == "selected"]
        needle = q.lower()
        for row in rows:
            card = _card(row, people, True, adults)
            if needle:
                blob = " ".join(
                    [
                        card["fields"].get("title") or "",
                        card["fields"].get("login") or "",
                        card["fields"].get("url") or "",
                        card["fields"].get("purpose") or "",
                        card["fields"].get("details") or "",
                        card["fields"].get("phone") or "",
                        card["fields"].get("account_no") or "",
                        card["fields"].get("call_info") or "",
                        card["kind_label"],
                    ]
                ).lower()
                if needle not in blob:
                    continue
            cards.append(card)
    add_kind = kind or "password"
    return render_template(
        "vault.html",
        opened=opened,
        cards=cards,
        q=q,
        scope=scope,
        kind=kind,
        kinds=KINDS,
        kind_labels=KIND_LABELS,
        add_kind=add_kind,
        add_label=KIND_ADD.get(add_kind, "Add a login"),
        add_one=KIND_ONE.get(add_kind, "Login"),
        adults=adults,
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
        if _wants_sheet() and reauth_ok():
            return _render_new(draft=fields, kind=_kind_from_request())
        return _render_index(draft=fields) if reauth_ok() else redirect(url_for("vault.index"))
    hid = household_id()
    kind = _kind_from_request()
    try:
        sealed = seal_fields(fields, hid)
        row = VaultEntry(
            household_id=hid,
            created_by=current_user.id,
            kind=kind,
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
        flash("Could not save that. Try Save again.", "danger")
        if _wants_sheet() and reauth_ok():
            return _render_new(draft=fields, kind=kind)
        return _render_index(draft=fields) if reauth_ok() else redirect(url_for("vault.index"))
    flash("Saved. Only you can see it until you share it.", "success")
    if _wants_sheet():
        return redirect(url_for("vault.detail", entry_id=row.id, next="sheet", saved=1))
    return redirect(url_for("vault.index"))


@vault_bp.route("/<int:entry_id>/edit", methods=["POST"])
@login_required
def edit(entry_id):
    _guard()
    if not reauth_ok():
        flash("Sign in again to change a login.", "warning")
        return redirect(url_for("vault.index"))
    hid = household_id()
    row = _entry_query().filter_by(id=entry_id).first_or_404()
    if not can_manage_entry(row, current_user):
        abort(403)
    if not can_view_entry(row, current_user):
        abort(403)
    fields = _form_fields()
    if not fields["title"]:
        flash("Give it a title.", "danger")
        if _wants_sheet():
            return redirect(url_for("vault.detail", entry_id=entry_id, next="sheet"))
        return redirect(url_for("vault.index"))
    sealed = seal_fields(fields, hid)
    for key, val in sealed.items():
        setattr(row, key, val)
    row.kind = _kind_from_request(kind_of(row))
    row.updated_at = datetime.utcnow()
    db.session.commit()
    flash("Saved.", "success")
    if _wants_sheet():
        return redirect(url_for("vault.detail", entry_id=entry_id, next="sheet", saved=1))
    return redirect(url_for("vault.index"))


@vault_bp.route("/<int:entry_id>/share", methods=["POST"])
@login_required
def share(entry_id):
    _guard()
    if not reauth_ok():
        flash("Sign in again to change who sees this.", "warning")
        return redirect(url_for("vault.index"))
    hid = household_id()
    row = _entry_query().filter_by(id=entry_id).first_or_404()
    if not can_manage_entry(row, current_user):
        abort(403)
    mode = _share_from_form()
    prev = (row.share_mode or "personal").strip().lower()
    row.share_mode = mode
    row.updated_at = datetime.utcnow()
    if mode == "personal" and prev != "personal":
        _revoke_live(row, hid)
    db.session.commit()
    flash("Who can see this is updated. Change it anytime.", "success")
    if _wants_sheet():
        return redirect(url_for("vault.detail", entry_id=entry_id, next="sheet", saved=1))
    return redirect(url_for("vault.index"))


@vault_bp.route("/new")
@login_required
def new():
    _guard()
    if not reauth_ok():
        flash("Sign in again to add a login.", "warning")
        return redirect(url_for("vault.index"))
    return _render_new(kind=_kind_from_request())


@vault_bp.route("/<int:entry_id>")
@login_required
def detail(entry_id):
    _guard()
    if not reauth_ok():
        flash("Sign in again to open the vault.", "warning")
        return redirect(url_for("vault.index"))
    ping = (request.args.get("saved") or "") == "1"
    return _render_detail(entry_id, ping_saved=ping)


def _sheet_back(entry_id):
    if _wants_sheet():
        return redirect(url_for("vault.detail", entry_id=entry_id, next="sheet", saved=1))
    return redirect(url_for("vault.index"))


@vault_bp.route("/<int:entry_id>/grant", methods=["POST"])
@login_required
def grant(entry_id):
    _guard()
    if not reauth_ok():
        flash("Sign in again to change who sees this.", "warning")
        return redirect(url_for("vault.index"))
    hid = household_id()
    row = _entry_query().filter_by(id=entry_id).first_or_404()
    if not can_manage_entry(row, current_user):
        abort(403)
    uid = _person_id(request.form.get("person"))
    if uid is None:
        flash("Pick someone.", "danger")
        return _sheet_back(entry_id)
    try:
        _give_access(row, hid, uid, request.form.get("for") or "forever")
    except ValueError:
        flash("That person cannot be given this.", "danger")
        return _sheet_back(entry_id)
    row.share_mode = "selected"
    row.updated_at = datetime.utcnow()
    db.session.commit()
    flash("They can see it for that long. Take it back anytime.", "success")
    return _sheet_back(entry_id)


@vault_bp.route("/<int:entry_id>/revoke/<int:user_id>", methods=["POST"])
@login_required
def revoke(entry_id, user_id):
    _guard()
    if not reauth_ok():
        flash("Sign in again to change who sees this.", "warning")
        return redirect(url_for("vault.index"))
    hid = household_id()
    row = _entry_query().filter_by(id=entry_id).first_or_404()
    if not can_manage_entry(row, current_user):
        abort(403)
    n = _revoke_live(row, hid, user_id)
    row.updated_at = datetime.utcnow()
    db.session.commit()
    flash("Taken back." if n else "They already did not have it.", "info")
    return _sheet_back(entry_id)


@vault_bp.route("/<int:entry_id>/extend/<int:user_id>", methods=["POST"])
@login_required
def extend(entry_id, user_id):
    _guard()
    if not reauth_ok():
        flash("Sign in again to change who sees this.", "warning")
        return redirect(url_for("vault.index"))
    hid = household_id()
    row = _entry_query().filter_by(id=entry_id).first_or_404()
    if not can_manage_entry(row, current_user):
        abort(403)
    try:
        _give_access(row, hid, user_id, request.form.get("for") or "1h")
    except ValueError:
        flash("That person cannot be given this.", "danger")
        return _sheet_back(entry_id)
    row.share_mode = "selected"
    row.updated_at = datetime.utcnow()
    db.session.commit()
    flash("Time updated from now.", "success")
    return _sheet_back(entry_id)


@vault_bp.route("/<int:entry_id>/seen", methods=["POST"])
@login_required
def seen(entry_id):
    _guard()
    if not reauth_ok():
        return {"ok": False}, 401
    row = _entry_query().filter_by(id=entry_id).first_or_404()
    if not can_view_entry(row, current_user):
        abort(403)
    action = (request.form.get("action") or request.args.get("action") or "view").strip().lower()
    if action not in (
        "view",
        "copy_login",
        "copy_secret",
        "copy_phone",
        "copy_account",
        "reveal",
        "open_site",
    ):
        action = "view"
    if int(row.created_by or 0) == int(current_user.id) and action == "view":
        return {"ok": True}
    try:
        log_vault_access(row, current_user, action)
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return {"ok": False}, 500
    return {"ok": True}


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
    if _wants_sheet():
        return render_template("vault_gone.html", ping_saved=True)
    return redirect(url_for("vault.index"))
