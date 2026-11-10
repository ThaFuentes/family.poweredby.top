"""Share files with the household, named people, or anyone holding the link."""
from __future__ import annotations

import json
import os
import secrets
import shutil
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import or_
from sqlalchemy.orm import selectinload
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from app.builddb.builddb import db
from app.builddb.table_households import Household
from app.builddb.table_shared_file_downloads import SharedFileDownload
from app.builddb.table_shared_file_events import SharedFileEvent
from app.builddb.table_shared_file_people import SharedFilePerson
from app.builddb.table_shared_files import SHARE_MODES, SharedFile
from app.builddb.table_shared_upload_sessions import ShareUploadSession
from app.builddb.table_users import User
from app.utils.crypto import (
    CHUNK_BYTES,
    append_chunk,
    send_file_stream,
    start_chunked_upload,
    write_encrypted_stream,
)
from app.utils.household import household_id
from app.utils.mail import send_mail
from app.utils.permissions import can, role_of

share_bp = Blueprint("share", __name__)

MAX_BYTES = 3 * 1024 * 1024 * 1024
UNLOCK_HOURS = 12
TRY_LIMIT = 8
TRY_WINDOW = 15 * 60

EXPIRY_CHOICES = (
    ("0", "Never"),
    ("1", "After 1 day"),
    ("3", "After 3 days"),
    ("7", "After 7 days"),
    ("14", "After 14 days"),
    ("30", "After 30 days"),
)

MODE_LABELS = {
    "family": "Family only — everyone in this household",
    "people": "Only certain people in this household",
    "link": "Anyone with the link",
    "password": "Anyone with the link + a password",
}
MODE_SHORT = {
    "family": "Family",
    "people": "People",
    "link": "Link",
    "password": "Password",
}

ALLOWED_EXT = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".heic",
    ".pdf",
    ".txt",
    ".csv",
    ".md",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".zip",
}
MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".heic": "image/heic",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".md": "text/plain",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".zip": "application/zip",
}


def _mail_sender(household) -> dict:
    """Which mailbox a share email leaves from, and where to set one up."""
    from app.utils.household_mail import household_mail_config
    from app.utils.mail import mail_config

    own = household_mail_config(household)
    platform = mail_config()
    if own is not None:
        label = f"this house's mailbox ({own['from_email']})"
        ready = True
    elif (
        platform.get("mode") == "smtp"
        and platform.get("smtp_host")
        and platform.get("from_email")
    ):
        label = f"the Family OS mailbox ({platform['from_email']})"
        ready = True
    else:
        label = ""
        ready = False
    return {
        "ready": ready,
        "label": label,
        "setup_url": url_for("members.sheet", panel="mail"),
        "can_setup": can("settings"),
    }


def _uploads_root() -> str:
    root = os.path.join(os.path.dirname(current_app.root_path), "uploads")
    os.makedirs(root, exist_ok=True)
    return root


def _guard_manage():
    """Kids do not share files. Adults in the house do."""
    if role_of() == "child" or not can("photo"):
        abort(403)


def _can_manage(row) -> bool:
    return int(row.created_by or 0) == int(current_user.id) or bool(
        getattr(current_user, "is_admin", False)
    )


def _by_token(token):
    return (
        SharedFile.query.options(selectinload(SharedFile.people))
        .filter_by(token=str(token or "")[:64])
        .first()
    )


def _row_or_404(file_id):
    return SharedFile.query.options(selectinload(SharedFile.people)).filter_by(
        id=file_id, household_id=household_id()
    ).first_or_404()


def _visible_rows(hid: int):
    q = SharedFile.query.filter_by(household_id=hid).options(
        selectinload(SharedFile.people)
    )
    if getattr(current_user, "is_admin", False):
        return q.order_by(SharedFile.id.desc()).limit(200).all()
    return (
        q.filter(
            or_(
                SharedFile.created_by == current_user.id,
                SharedFile.share_mode == "family",
                SharedFile.people.any(SharedFilePerson.user_id == current_user.id),
            )
        )
        .order_by(SharedFile.id.desc())
        .limit(200)
        .all()
    )


def _size_label(n) -> str:
    try:
        size = int(n or 0)
    except (TypeError, ValueError):
        size = 0
    if size <= 0:
        return "unknown size"
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    if size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{size / (1024 * 1024 * 1024):.1f} GB"


def _upload_limit() -> int:
    try:
        configured = int(current_app.config.get("SHARE_UPLOAD_MAX_BYTES") or MAX_BYTES)
    except (TypeError, ValueError):
        configured = MAX_BYTES
    return configured if configured > 0 else MAX_BYTES


def _clean_filename(raw_name: str) -> tuple[str, str]:
    """Return (original_name, ext). Ext comes from the raw name so accents survive."""
    base = str(raw_name or "").replace("\\", "/").split("/")[-1]
    ext = os.path.splitext(base)[1].lower()
    clean = secure_filename(base)[:180]
    if not clean:
        clean = "file" + ext
    elif ext and not clean.lower().endswith(ext):
        clean = (os.path.splitext(clean)[0] or "file")[: max(1, 180 - len(ext))] + ext
    return clean[:200], ext


def _clean_people(hid: int, owner_id: int, values) -> list[int]:
    chosen: list[int] = []
    for raw in values or []:
        if not str(raw).isdigit():
            continue
        uid = int(raw)
        if uid > 0 and uid != int(owner_id) and uid not in chosen:
            chosen.append(uid)
    if not chosen:
        return []
    valid = {
        u.id
        for u in User.query.filter_by(household_id=hid, is_active=True)
        .filter(User.id.in_(chosen))
        .all()
    }
    return [uid for uid in chosen if uid in valid]


def _people_from_form(hid: int, owner_id: int) -> list[int]:
    return _clean_people(hid, owner_id, request.form.getlist("people"))


def _mode_from_form(default: str = "family") -> str:
    mode = (request.form.get("share_mode") or default).strip().lower()
    return mode if mode in SHARE_MODES else "family"


def _expiry_from_form(keep=None):
    """None means the link never ends. "keep" leaves the current end date."""
    raw = (request.form.get("expires_days") or "").strip().lower()
    if raw in ("", "keep"):
        return keep
    try:
        days = int(raw)
    except (TypeError, ValueError):
        return keep
    if days <= 0:
        return None
    return datetime.utcnow() + timedelta(days=min(days, 365))


UPLOAD_TTL_HOURS = 24
MAX_LIVE_UPLOADS = 5
_upload_locks: dict[str, threading.Lock] = {}
_upload_locks_guard = threading.Lock()


def _upload_lock(upload_id: str) -> threading.Lock:
    with _upload_locks_guard:
        return _upload_locks.setdefault(str(upload_id), threading.Lock())


def _expiry_days(raw) -> int:
    try:
        days = int(str(raw if raw not in (None, "") else "0").strip())
    except (TypeError, ValueError):
        return 0
    return max(0, min(days, 365))


def _expiry_at(days: int):
    return datetime.utcnow() + timedelta(days=int(days)) if int(days or 0) > 0 else None


def _session_file(row) -> Path:
    root = Path(_uploads_root()).resolve()
    rel = Path(str(row.stored_path or ""))
    if rel.is_absolute() or ".." in rel.parts or len(rel.parts) < 4:
        abort(404)
    if rel.parts[0] != str(row.household_id) or rel.parts[1] != "share_incoming":
        abort(404)
    path = (root / rel).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        abort(404)
    return path


def _drop_upload(row) -> None:
    try:
        shutil.rmtree(_session_file(row).parent, ignore_errors=True)
    except Exception:
        pass
    try:
        db.session.delete(row)
    except Exception:
        pass


def _prune_uploads(hid: int) -> None:
    """Drop abandoned sessions and cap how many one person can leave open."""
    cutoff = datetime.utcnow() - timedelta(hours=UPLOAD_TTL_HOURS)
    stale = (
        ShareUploadSession.query.filter(
            ShareUploadSession.household_id == int(hid),
            ShareUploadSession.updated_at < cutoff,
        )
        .all()
    )
    mine = (
        ShareUploadSession.query.filter_by(
            household_id=int(hid), created_by=int(current_user.id)
        )
        .order_by(ShareUploadSession.updated_at.desc())
        .all()
    )
    extras = mine[MAX_LIVE_UPLOADS:]
    seen = set()
    for row in list(stale) + list(extras):
        if row.id in seen:
            continue
        seen.add(row.id)
        _drop_upload(row)
    if seen:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()


def _upload_or_error(upload_id):
    row = db.session.get(ShareUploadSession, str(upload_id or ""))
    if row is None or int(row.household_id) != int(household_id()):
        return None, (jsonify(ok=False, error="That upload is no longer here."), 404)
    if int(row.created_by or 0) != int(current_user.id):
        return None, (jsonify(ok=False, error="That upload belongs to someone else."), 403)
    if row.updated_at and row.updated_at < datetime.utcnow() - timedelta(hours=UPLOAD_TTL_HOURS):
        _drop_upload(row)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
        return None, (
            jsonify(ok=False, error="That partial upload expired. Start it again."),
            410,
        )
    return row, None


def _room_for(size: int) -> bool:
    try:
        free = shutil.disk_usage(_uploads_root()).free
    except OSError:
        return True
    # Fernet adds about a third, plus room for the final file before it moves.
    return free >= int(int(size) * 1.45) + 64 * 1024 * 1024


def _expired(row) -> bool:
    exp = getattr(row, "expires_at", None)
    return bool(exp) and exp <= datetime.utcnow()


def _expiry_label(exp) -> str:
    if not exp:
        return ""
    now = datetime.utcnow()
    if exp <= now:
        return "expired"
    seconds = (exp - now).total_seconds()
    if seconds < 3600:
        return "ends in under an hour"
    if seconds < 48 * 3600:
        return f"ends in {int(round(seconds / 3600))} hours"
    return f"ends in {int(round(seconds / 86400))} days"


def _resolve_path(row) -> Path:
    root = Path(_uploads_root()).resolve()
    rel = Path(str(row.stored_path or ""))
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        abort(404)
    if rel.parts[0] != str(row.household_id):
        abort(404)
    path = (root / rel).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        abort(404)
    if not path.is_file():
        abort(404)
    return path


def _unlink(row):
    try:
        path = _resolve_path(row)
        path.unlink(missing_ok=True)
    except Exception:
        pass


def _unlock_key(token: str) -> str:
    return f"share_ok_{str(token)[:64]}"


def _unlocked(row) -> bool:
    try:
        ts = float(session.get(_unlock_key(row.token)) or 0)
    except (TypeError, ValueError):
        return False
    return ts > 0 and (time.time() - ts) < UNLOCK_HOURS * 3600


def _tries(token: str) -> int:
    raw = session.get("share_pw_tries") or {}
    if not isinstance(raw, dict):
        raw = {}
    now = time.time()
    stamps = [
        float(t) for t in (raw.get(token) or []) if now - float(t) < TRY_WINDOW
    ]
    raw[token] = stamps
    # Keep the cookie small: only the most recent few links remember tries.
    if len(raw) > 8:
        raw = dict(list(raw.items())[-8:])
    session["share_pw_tries"] = raw
    return len(stamps)


def _remember_try(token: str) -> None:
    raw = session.get("share_pw_tries") or {}
    if not isinstance(raw, dict):
        raw = {}
    raw.setdefault(token, []).append(time.time())
    session["share_pw_tries"] = raw


def _may_open(row) -> bool:
    """Family / people links need the signed-in household. Link modes do not."""
    mode = (row.share_mode or "").strip().lower()
    if mode in ("link", "password"):
        return True
    if not getattr(current_user, "is_authenticated", False):
        return False
    if int(getattr(current_user, "household_id", 0) or 0) != int(row.household_id):
        return False
    if mode == "family":
        return True
    if mode == "people":
        if int(row.created_by or 0) == int(current_user.id):
            return True
        if getattr(current_user, "is_admin", False):
            return True
        return any(int(p.user_id) == int(current_user.id) for p in row.people)
    return False


def _card(row, names: dict | None = None, *, public: bool = False) -> dict:
    names = names or {}
    people_ids = [int(p.user_id) for p in (row.people or [])]
    card = {
        "row": row,
        "token": row.token,
        "title": (row.title or row.original_name or "Shared file")[:160],
        "filename": row.original_name or "file",
        "size": _size_label(row.size_bytes),
        "mode_label": MODE_LABELS.get(row.share_mode, row.share_mode),
        "short_mode": MODE_SHORT.get(row.share_mode, row.share_mode),
        "people_ids": people_ids,
        "people_names": [
            names.get(uid) or names.get(str(uid)) or "someone" for uid in people_ids
        ],
        "url": url_for("share.public", token=row.token, _external=True),
        "downloads": int(row.download_count or 0),
        "revoked": bool(row.revoked_at),
        "expired": _expired(row),
        "expiry_label": _expiry_label(row.expires_at),
        "can_manage": False if public else _can_manage(row),
        "log": [],
    }
    return card


def _attach_logs(cards, names: dict) -> None:
    ids = [int(c["row"].id) for c in cards if c["can_manage"]]
    if not ids:
        return
    rows = (
        SharedFileDownload.query.filter(SharedFileDownload.file_id.in_(ids))
        .order_by(SharedFileDownload.id.desc())
        .limit(600)
        .all()
    )
    grouped: dict[int, list[dict]] = {}
    for entry in rows:
        bucket = grouped.setdefault(int(entry.file_id), [])
        if len(bucket) >= 6:
            continue
        bucket.append(
            {
                "who": names.get(entry.user_id)
                or ("someone not signed in" if not entry.user_id else "a family member"),
                "ip": entry.ip or "",
                "when": entry.downloaded_at,
            }
        )
    for card in cards:
        card["log"] = grouped.get(int(card["row"].id), [])


def _log_download(row) -> None:
    user_id = None
    try:
        if getattr(current_user, "is_authenticated", False):
            user_id = int(current_user.id)
    except Exception:
        user_id = None
    try:
        agent = (request.user_agent.string or "")[:255]
    except Exception:
        agent = ""
    db.session.add(
        SharedFileDownload(
            household_id=int(row.household_id),
            file_id=int(row.id),
            user_id=user_id,
            ip=(request.remote_addr or "")[:64],
            user_agent=agent,
        )
    )


def _when_label(exp) -> str:
    return exp.strftime("%Y-%m-%d %H:%M UTC") if exp else "never"


def _record_event(row, kind: str, detail: str = "", *, ok: bool = True) -> None:
    """Record an email or link change. Never let logging break the action."""
    try:
        user_id = (
            int(current_user.id)
            if getattr(current_user, "is_authenticated", False)
            else None
        )
    except Exception:
        user_id = None
    try:
        db.session.add(
            SharedFileEvent(
                household_id=int(row.household_id),
                file_id=int(row.id),
                user_id=user_id,
                kind=str(kind)[:20],
                detail=(detail or "")[:500],
                ok=bool(ok),
                ip=(request.remote_addr or "")[:64],
            )
        )
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass


def _stream_size(stream) -> int | None:
    try:
        here = stream.tell()
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(here)
        return max(0, int(size))
    except Exception:
        return None


@share_bp.after_request
def _share_headers(response):
    response.headers["Cache-Control"] = "private, no-store, no-cache, must-revalidate"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@share_bp.route("/share/")
@login_required
def index():
    _guard_manage()
    hid = household_id()
    _prune_uploads(hid)
    everyone = {
        u.id: (u.name or u.username)
        for u in User.query.filter_by(household_id=hid).all()
    }
    people = (
        User.query.filter_by(household_id=hid, is_active=True)
        .filter(User.id != current_user.id)
        .order_by(User.name.asc(), User.username.asc())
        .all()
    )
    cards = [_card(row, everyone) for row in _visible_rows(hid)]
    _attach_logs(cards, everyone)
    return render_template(
        "share.html",
        cards=cards,
        people=people,
        mode_labels=MODE_LABELS,
        expiry_choices=EXPIRY_CHOICES,
        upload_limit=_size_label(_upload_limit()),
        mail_sender=_mail_sender(db.session.get(Household, hid)),
    )


@share_bp.route("/share/upload", methods=["POST"])
@login_required
def upload():
    _guard_manage()
    hid = household_id()
    upload_file = request.files.get("file")
    if upload_file is None or not (upload_file.filename or "").strip():
        flash("Pick a file to upload.", "danger")
        return redirect(url_for("share.index"))
    orig, ext = _clean_filename(upload_file.filename)
    if ext not in ALLOWED_EXT:
        flash(
            "That kind of file cannot be shared here. Photos, PDFs, text, Word, Excel, and ZIP are fine.",
            "danger",
        )
        return redirect(url_for("share.index"))

    limit = _upload_limit()
    announced = _stream_size(upload_file.stream)
    if announced is not None and announced > limit:
        flash(
            f"That file is {_size_label(announced)}. One upload can be up to {_size_label(limit)}.",
            "danger",
        )
        return redirect(url_for("share.index"))

    mode = _mode_from_form()
    password = (request.form.get("password") or "").strip()
    if mode == "password" and len(password) < 4:
        flash("Give the link a password of at least 4 characters.", "danger")
        return redirect(url_for("share.index"))
    chosen = _people_from_form(hid, current_user.id) if mode == "people" else []
    if mode == "people" and not chosen:
        flash("Pick at least one person for “Only certain people”.", "danger")
        return redirect(url_for("share.index"))

    token = secrets.token_urlsafe(24)
    folder = os.path.join(_uploads_root(), str(hid), "share", token)
    os.makedirs(folder, exist_ok=True)
    name = secrets.token_hex(8) + ext + ".enc"
    stored = os.path.join(folder, name)
    try:
        written = write_encrypted_stream(stored, upload_file.stream)
    except Exception as exc:
        try:
            os.unlink(stored)
        except OSError:
            pass
        print(f"[share] upload failed: {exc}", flush=True)
        flash("Could not save that upload. Try again.", "danger")
        return redirect(url_for("share.index"))
    if written <= 0:
        try:
            os.unlink(stored)
        except OSError:
            pass
        flash("That file was empty.", "danger")
        return redirect(url_for("share.index"))
    if written > limit:
        try:
            os.unlink(stored)
        except OSError:
            pass
        flash(
            f"That file is {_size_label(written)}. One upload can be up to {_size_label(limit)}.",
            "danger",
        )
        return redirect(url_for("share.index"))

    title = (request.form.get("title") or "").strip()[:200]
    if not title:
        title = (os.path.splitext(orig)[0] or orig)[:200]
    row = SharedFile(
        household_id=hid,
        created_by=current_user.id,
        title=title,
        original_name=orig,
        stored_path=f"{hid}/share/{token}/{name}",
        mime=MIME_BY_EXT.get(ext, "application/octet-stream"),
        size_bytes=written,
        token=token,
        share_mode=mode,
        password_hash=generate_password_hash(password) if mode == "password" else None,
        expires_at=_expiry_from_form(),
    )
    db.session.add(row)
    try:
        db.session.flush()
        for uid in chosen:
            db.session.add(
                SharedFilePerson(household_id=hid, file_id=row.id, user_id=uid)
            )
        db.session.commit()
    except Exception as exc:
        try:
            db.session.rollback()
        except Exception:
            pass
        try:
            os.unlink(stored)
        except OSError:
            pass
        print(f"[share] upload failed: {exc}", flush=True)
        flash("Could not save that upload. Try again.", "danger")
        return redirect(url_for("share.index"))
    _record_event(
        row,
        "create",
        f"Link created ({MODE_SHORT.get(row.share_mode, row.share_mode)})",
    )
    flash("Uploaded. Copy or email the link to whoever needs it.", "success")
    return redirect(url_for("share.index") + f"#f{row.id}")


@share_bp.route("/share/upload/session", methods=["POST"])
@login_required
def upload_init():
    """Start a resumable upload: validate the file and remember the share settings."""
    _guard_manage()
    hid = int(household_id())
    _prune_uploads(hid)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = request.form

    raw_name = str(data.get("name") or "").strip()[:255]
    if not raw_name:
        return jsonify(ok=False, error="Pick a file to upload."), 400
    orig, ext = _clean_filename(raw_name)
    if ext not in ALLOWED_EXT:
        return (
            jsonify(
                ok=False,
                error="That kind of file cannot be shared here. Photos, PDFs, text, Word, Excel, and ZIP are fine.",
            ),
            400,
        )
    try:
        size = int(data.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    limit = _upload_limit()
    if size <= 0:
        return jsonify(ok=False, error="That file was empty."), 400
    if size > limit:
        return (
            jsonify(
                ok=False,
                error=f"That file is {_size_label(size)}. One upload can be up to {_size_label(limit)}.",
            ),
            400,
        )
    if not _room_for(size):
        return (
            jsonify(
                ok=False,
                error="The server does not have enough free disk space for that file right now.",
            ),
            507,
        )

    mode = str(data.get("share_mode") or "family").strip().lower()
    if mode not in SHARE_MODES:
        mode = "family"
    password = str(data.get("password") or "").strip()
    if mode == "password" and len(password) < 4:
        return jsonify(ok=False, error="Give the link a password of at least 4 characters."), 400
    raw_people = data.get("people") or []
    if isinstance(raw_people, str):
        raw_people = [raw_people]
    chosen = _clean_people(hid, current_user.id, raw_people) if mode == "people" else []
    if mode == "people" and not chosen:
        return jsonify(ok=False, error="Pick at least one person for “Only certain people”."), 400

    title = str(data.get("title") or "").strip()[:200]
    if not title:
        title = (os.path.splitext(orig)[0] or orig)[:200]
    upload_id = secrets.token_urlsafe(24)
    rel = f"{hid}/share_incoming/{upload_id}/data.enc"
    try:
        start_chunked_upload(os.path.join(_uploads_root(), rel))
    except Exception as exc:
        print(f"[share] upload start failed: {exc}", flush=True)
        return jsonify(ok=False, error="Could not start that upload. Try again."), 503

    now = datetime.utcnow()
    row = ShareUploadSession(
        id=upload_id,
        household_id=hid,
        created_by=current_user.id,
        original_name=orig,
        ext=ext,
        title=title,
        mime=MIME_BY_EXT.get(ext, "application/octet-stream"),
        share_mode=mode,
        password_hash=generate_password_hash(password) if mode == "password" else None,
        expiry_days=_expiry_days(data.get("expires_days")),
        people_json=json.dumps(chosen),
        size_bytes=size,
        received_bytes=0,
        stored_path=rel,
        created_at=now,
        updated_at=now,
    )
    try:
        db.session.add(row)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        try:
            shutil.rmtree(os.path.join(_uploads_root(), str(hid), "share_incoming", upload_id), ignore_errors=True)
        except Exception:
            pass
        print(f"[share] upload session failed: {exc}", flush=True)
        return jsonify(ok=False, error="Could not start that upload. Try again."), 503

    return jsonify(
        ok=True,
        upload_id=upload_id,
        chunk_size=CHUNK_BYTES,
        offset=0,
        size=size,
        name=orig,
        title=title,
        mode=mode,
    )


@share_bp.route("/share/upload/session/<upload_id>", methods=["GET"])
@login_required
def upload_status(upload_id):
    _guard_manage()
    row, error = _upload_or_error(upload_id)
    if error:
        return error
    return jsonify(
        ok=True,
        upload_id=row.id,
        offset=int(row.received_bytes or 0),
        size=int(row.size_bytes or 0),
        chunk_size=CHUNK_BYTES,
        name=row.original_name,
        title=row.title,
        mode=row.share_mode,
    )


@share_bp.route("/share/upload/session/<upload_id>/chunk", methods=["PUT"])
@login_required
def upload_chunk(upload_id):
    """Append one plaintext chunk at the exact offset the server last acknowledged."""
    _guard_manage()
    row, error = _upload_or_error(upload_id)
    if error:
        return error
    try:
        offset = int(request.args.get("offset", "-1"))
    except (TypeError, ValueError):
        offset = -1
    with _upload_lock(row.id):
        try:
            db.session.refresh(row)
        except Exception:
            return jsonify(ok=False, error="That upload is no longer here."), 410
        have = int(row.received_bytes or 0)
        if offset != have:
            return jsonify(ok=False, offset=have, error="Wrong offset."), 409
        length = request.content_length
        if length is not None and length > CHUNK_BYTES:
            return jsonify(ok=False, error="That piece is too large."), 413
        data = request.get_data(cache=False)
        if not data:
            return jsonify(ok=False, error="Empty piece."), 400
        if len(data) > CHUNK_BYTES:
            return jsonify(ok=False, error="That piece is too large."), 413
        if have + len(data) > int(row.size_bytes or 0):
            return jsonify(ok=False, error="That is more data than the file size."), 400
        if not _room_for(int(row.size_bytes or 0) - have - len(data)):
            return jsonify(ok=False, error="The server is out of disk space for this upload."), 507

        path = _session_file(row)
        try:
            before = path.stat().st_size
        except OSError:
            return jsonify(ok=False, error="That upload is no longer on disk."), 410
        try:
            append_chunk(str(path), data)
        except Exception as exc:
            try:
                os.truncate(path, before)
            except OSError:
                pass
            print(f"[share] chunk write failed: {exc}", flush=True)
            return jsonify(ok=False, error="Could not save that piece. Retrying may fix it."), 503

        row.received_bytes = have + len(data)
        row.updated_at = datetime.utcnow()
        try:
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            try:
                os.truncate(path, before)
            except OSError:
                pass
            print(f"[share] chunk offset failed: {exc}", flush=True)
            return jsonify(ok=False, error="Could not record that piece. Retrying may fix it."), 503
    return jsonify(ok=True, offset=row.received_bytes)


@share_bp.route("/share/upload/session/<upload_id>/finish", methods=["POST"])
@login_required
def upload_finish(upload_id):
    _guard_manage()
    row, error = _upload_or_error(upload_id)
    if error:
        return error
    with _upload_lock(row.id):
        try:
            db.session.refresh(row)
        except Exception:
            return jsonify(ok=False, error="That upload is no longer here."), 410
        have = int(row.received_bytes or 0)
        size = int(row.size_bytes or 0)
        if have != size:
            return jsonify(ok=False, offset=have, error="That upload is not complete yet."), 409
        if size <= 0:
            return jsonify(ok=False, error="That file was empty."), 400

        hid = int(row.household_id)
        token = secrets.token_urlsafe(24)
        folder = os.path.join(_uploads_root(), str(hid), "share", token)
        os.makedirs(folder, exist_ok=True)
        name = secrets.token_hex(8) + row.ext + ".enc"
        src = _session_file(row)
        dst = os.path.join(folder, name)
        try:
            os.replace(src, dst)
        except OSError as exc:
            shutil.rmtree(folder, ignore_errors=True)
            print(f"[share] finish move failed: {exc}", flush=True)
            return jsonify(ok=False, error="Could not finish that upload. Try again."), 503

        shared = SharedFile(
            household_id=hid,
            created_by=row.created_by,
            title=row.title,
            original_name=row.original_name,
            stored_path=f"{hid}/share/{token}/{name}",
            mime=row.mime,
            size_bytes=size,
            token=token,
            share_mode=row.share_mode,
            password_hash=row.password_hash,
            expires_at=_expiry_at(row.expiry_days),
        )
        try:
            db.session.add(shared)
            db.session.flush()
            for uid in json.loads(row.people_json or "[]"):
                db.session.add(
                    SharedFilePerson(household_id=hid, file_id=shared.id, user_id=int(uid))
                )
            db.session.delete(row)
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            try:
                os.replace(dst, src)
            except OSError:
                pass
            print(f"[share] finish failed: {exc}", flush=True)
            return jsonify(ok=False, error="Could not finish that upload. Try again."), 503

    try:
        shutil.rmtree(os.path.dirname(src), ignore_errors=True)
    except Exception:
        pass
    _record_event(
        shared,
        "create",
        f"Link created ({MODE_SHORT.get(shared.share_mode, shared.share_mode)})",
    )
    return jsonify(
        ok=True,
        file_id=shared.id,
        redirect=url_for("share.index") + f"#f{shared.id}",
    )


@share_bp.route("/share/upload/session/<upload_id>", methods=["DELETE"])
@login_required
def upload_cancel(upload_id):
    _guard_manage()
    row, error = _upload_or_error(upload_id)
    if error:
        return error
    _drop_upload(row)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
    return jsonify(ok=True)


@share_bp.route("/share/<int:file_id>/activity")
@login_required
def activity(file_id):
    """One timeline per file: downloads, emails sent, and link changes."""
    row = _row_or_404(file_id)
    if not _can_manage(row):
        abort(403)
    hid = int(row.household_id)
    names = {
        u.id: (u.name or u.username)
        for u in User.query.filter_by(household_id=hid).all()
    }
    downloads = (
        SharedFileDownload.query.filter_by(file_id=row.id, household_id=hid)
        .order_by(SharedFileDownload.id.desc())
        .limit(300)
        .all()
    )
    events = (
        SharedFileEvent.query.filter_by(file_id=row.id, household_id=hid)
        .order_by(SharedFileEvent.id.desc())
        .limit(300)
        .all()
    )
    items = []
    for d in downloads:
        items.append(
            {
                "when": d.downloaded_at,
                "kind": "download",
                "label": "Downloaded",
                "who": names.get(d.user_id)
                or ("someone not signed in" if not d.user_id else "a family member"),
                "detail": "",
                "ip": d.ip or "",
            }
        )
    labels = {
        "email": ("Email sent", "Email failed"),
        "access": ("Link changed", "Link changed"),
        "revoke": ("Link turned off", "Link turned off"),
        "create": ("Link created", "Link created"),
    }
    for e in events:
        good, bad = labels.get(e.kind, ("Updated", "Updated"))
        items.append(
            {
                "when": e.created_at,
                "kind": e.kind,
                "label": good if e.ok else bad,
                "who": names.get(e.user_id) or "someone",
                "detail": e.detail or "",
                "ip": e.ip or "",
            }
        )
    items.sort(
        key=lambda x: (x["when"] is not None, x["when"] or datetime.min),
        reverse=True,
    )
    counts = {
        "downloads": SharedFileDownload.query.filter_by(
            file_id=row.id, household_id=hid
        ).count(),
        "emails": SharedFileEvent.query.filter_by(
            file_id=row.id, household_id=hid, kind="email"
        ).count(),
        "changes": SharedFileEvent.query.filter(
            SharedFileEvent.file_id == row.id,
            SharedFileEvent.household_id == hid,
            SharedFileEvent.kind.in_(("access", "revoke", "create")),
        ).count(),
    }
    return render_template(
        "share_activity.html",
        row=row,
        items=items,
        counts=counts,
        size=_size_label(row.size_bytes),
        mode_label=MODE_LABELS.get(row.share_mode, row.share_mode),
        expired=_expired(row),
        expiry_label=_expiry_label(row.expires_at),
    )


@share_bp.route("/share/<int:file_id>/access", methods=["POST"])
@login_required
def set_access(file_id):
    _guard_manage()
    hid = household_id()
    row = _row_or_404(file_id)
    if not _can_manage(row):
        abort(403)
    mode = _mode_from_form(row.share_mode or "family")
    password = (request.form.get("password") or "").strip()
    if mode == "password":
        if password:
            if len(password) < 4:
                flash("Give the link a password of at least 4 characters.", "danger")
                return redirect(url_for("share.index") + f"#f{row.id}")
            row.password_hash = generate_password_hash(password)
        elif not row.password_hash:
            flash("Give the link a password of at least 4 characters.", "danger")
            return redirect(url_for("share.index") + f"#f{row.id}")
    else:
        row.password_hash = None

    chosen = _people_from_form(hid, current_user.id) if mode == "people" else []
    if mode == "people" and not chosen:
        flash("Pick at least one person for “Only certain people”.", "danger")
        return redirect(url_for("share.index") + f"#f{row.id}")

    before_mode = row.share_mode
    before_password = bool(row.password_hash)
    before_expiry = row.expires_at
    before_revoked = bool(row.revoked_at)
    before_people = sorted(int(p.user_id) for p in (row.people or []))

    row.share_mode = mode
    row.expires_at = _expiry_from_form(keep=row.expires_at)
    for person in list(row.people or []):
        db.session.delete(person)
    db.session.flush()
    for uid in chosen:
        db.session.add(
            SharedFilePerson(household_id=hid, file_id=row.id, user_id=uid)
        )
    # Changing who can open it also turns a revoked link back on.
    row.revoked_at = None
    row.updated_at = datetime.utcnow()
    db.session.commit()

    parts = []
    if (row.share_mode or "") != (before_mode or ""):
        old = MODE_SHORT.get(before_mode, before_mode)
        new = MODE_SHORT.get(row.share_mode, row.share_mode)
        parts.append(f"access {old} → {new}")
    if row.share_mode == "password" and password:
        parts.append("password set")
    elif before_password and row.share_mode != "password":
        parts.append("password removed")
    if row.expires_at != before_expiry:
        parts.append(f"expiry {_when_label(before_expiry)} → {_when_label(row.expires_at)}")
    if sorted(int(p.user_id) for p in (row.people or [])) != before_people:
        parts.append("people list updated")
    if before_revoked:
        parts.append("link turned back on")
    if not parts:
        parts.append("saved with no visible change")
    _record_event(row, "access", "; ".join(parts))

    flash("Link updated.", "success")
    return redirect(url_for("share.index") + f"#f{row.id}")


@share_bp.route("/share/<int:file_id>/send", methods=["POST"])
@login_required
def send_link(file_id):
    """Email the link from the household mailbox. The password is never emailed."""
    _guard_manage()
    row = _row_or_404(file_id)
    if not _can_manage(row):
        abort(403)
    if row.revoked_at:
        flash("That link is turned off. Turn it back on before sending it.", "warning")
        return redirect(url_for("share.index") + f"#f{row.id}")
    if _expired(row):
        flash("That link has expired. Set a new end date, then send it.", "warning")
        return redirect(url_for("share.index") + f"#f{row.id}")
    to_email = (request.form.get("email") or "").strip()[:180]
    local, _, domain = to_email.partition("@")
    if not local or "." not in domain:
        flash("Enter a real email address.", "danger")
        return redirect(url_for("share.index") + f"#f{row.id}")

    household = db.session.get(Household, row.household_id)
    sender = _mail_sender(household)
    house_name = (getattr(household, "name", None) or "the household").strip()
    link = url_for("share.public", token=row.token, _external=True)
    lines = [
        f"{row.title}",
        "",
        "Open or download it here:",
        link,
        "",
    ]
    if row.share_mode == "password":
        lines.append("This link asks for a password. Ask whoever shared it for that separately.")
    elif row.share_mode == "family":
        lines.append("You need to be signed in to this household to open it.")
    if row.expires_at:
        lines.append(f"The link stops working after {row.expires_at.strftime('%Y-%m-%d %H:%M UTC')}.")
    note = (request.form.get("note") or "").strip()[:500]
    if note:
        lines += ["", note]
    lines += ["", f"Sent from {house_name} on Family OS."]
    ok, message = send_mail(
        to_email,
        f"{row.title} — shared from {house_name}",
        "\n".join(lines),
        household=household,
    )
    _record_event(
        row,
        "email",
        f"to {to_email}" + ("" if ok else f" — {message[:220]}"),
        ok=ok,
    )
    if not sender["ready"]:
        setup = (
            "Add this house's SMTP in People → Mailbox."
            if sender["can_setup"]
            else "Ask a leader to add a mailbox in People → Mailbox."
        )
        message = (
            f"{message} {setup} "
            "The site owner can also set the platform mailbox at /platform/email."
        )
    flash(message, "success" if ok else "danger")
    return redirect(url_for("share.index") + f"#f{row.id}")


@share_bp.route("/share/<int:file_id>/revoke", methods=["POST"])
@login_required
def revoke(file_id):
    _guard_manage()
    row = _row_or_404(file_id)
    if not _can_manage(row):
        abort(403)
    row.revoked_at = datetime.utcnow()
    row.updated_at = datetime.utcnow()
    db.session.commit()
    _record_event(row, "revoke", "Link turned off")
    flash("Link turned off. Nobody can download it from that link now.", "info")
    return redirect(url_for("share.index") + f"#f{row.id}")


@share_bp.route("/share/<int:file_id>/delete", methods=["POST"])
@login_required
def delete(file_id):
    _guard_manage()
    row = _row_or_404(file_id)
    if not _can_manage(row):
        abort(403)
    _unlink(row)
    db.session.delete(row)
    db.session.commit()
    flash("File removed.", "info")
    return redirect(url_for("share.index"))


@share_bp.route("/s/<token>")
def public(token):
    row = _by_token(token)
    if row is None:
        abort(404)
    if row.revoked_at:
        return render_template("share_public.html", gone=True), 410
    card = _card(row, public=True)
    if _expired(row):
        return render_template("share_public.html", c=card, expired=True), 410
    if (row.share_mode or "") == "password" and not _unlocked(row):
        return render_template("share_public.html", c=card, needs_password=True)
    if not _may_open(row):
        return render_template("share_public.html", c=card, denied=True), 403
    return render_template("share_public.html", c=card)


@share_bp.route("/s/<token>/unlock", methods=["POST"])
def unlock(token):
    row = _by_token(token)
    if row is None:
        abort(404)
    if row.revoked_at:
        return render_template("share_public.html", gone=True), 410
    card = _card(row, public=True)
    if _expired(row):
        return render_template("share_public.html", c=card, expired=True), 410
    if (row.share_mode or "") != "password" or not row.password_hash:
        return redirect(url_for("share.public", token=row.token))
    if _tries(row.token) >= TRY_LIMIT:
        return (
            render_template(
                "share_public.html",
                c=card,
                needs_password=True,
                error="Too many tries. Wait 15 minutes and try again.",
            ),
            429,
        )
    password = request.form.get("password") or ""
    if not password or not check_password_hash(row.password_hash, password):
        _remember_try(row.token)
        return (
            render_template(
                "share_public.html",
                c=card,
                needs_password=True,
                error="That password did not work.",
            ),
            401,
        )
    session[_unlock_key(row.token)] = time.time()
    return redirect(url_for("share.public", token=row.token))


@share_bp.route("/s/<token>/download")
def download(token):
    row = _by_token(token)
    if row is None:
        abort(404)
    if row.revoked_at:
        abort(410)
    if _expired(row):
        abort(410)
    if (row.share_mode or "") == "password" and not _unlocked(row):
        return redirect(url_for("share.public", token=row.token))
    if not _may_open(row):
        abort(403)
    path = _resolve_path(row)
    try:
        row.download_count = int(row.download_count or 0) + 1
        row.last_download_at = datetime.utcnow()
        _log_download(row)
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
    return send_file_stream(
        str(path),
        row.mime or "application/octet-stream",
        row.original_name or "file",
        length=row.size_bytes,
    )
