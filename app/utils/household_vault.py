"""Optional per-household data lock.

Leaders may set a memorable master key at start: a word, a dash, then their
secret — example FAMOS-ourphrase. We never store the phrase. Salt + a check
token live on the household. The session cookie holds a random ticket while
unlocked. The derived Fernet stays in a file outside the document root.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import TYPE_CHECKING

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy.orm.attributes import flag_modified

if TYPE_CHECKING:
    from app.builddb.table_households import Household

LOCK_RE = re.compile(r"^([A-Za-z]{4,12})-(.{5,80})$")
CHECK_PLAIN = b"family-os-vault-v1"
SESSION_HID = "family_vault_hid"
SESSION_KEY = "family_vault_fernet"
FORMAT_HINT = "Use a word, a dash, then your secret. Example: FAMOS-ourphrase"
_UNLOCK_DAYS = 400


def _unlock_dir() -> Path:
    override = (os.getenv("FAMILY_VAULT_UNLOCK_DIR") or "").strip()
    if override:
        return Path(override)
    return Path.home() / ".config" / "poweredbytop" / "family-vault-unlocks"


def _ticket_path(ticket: str) -> Path:
    digest = hashlib.sha256(ticket.encode("utf-8")).hexdigest()
    return _unlock_dir() / digest


def _save_unlock(household_id: int, key: str) -> str:
    folder = _unlock_dir()
    folder.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(folder, 0o700)
    except OSError:
        pass
    ticket = secrets.token_urlsafe(32)
    payload = json.dumps(
        {
            "hid": int(household_id),
            "key": key,
            "exp": int(time.time()) + _UNLOCK_DAYS * 86400,
        }
    )
    path = _ticket_path(ticket)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(payload)
    return ticket


def _load_unlock(ticket: str, household_id: int) -> str | None:
    if not ticket or not isinstance(ticket, str):
        return None
    path = _ticket_path(ticket)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    try:
        if int(payload.get("hid") or 0) != int(household_id):
            return None
        if int(payload.get("exp") or 0) < int(time.time()):
            path.unlink(missing_ok=True)
            return None
    except (TypeError, ValueError):
        return None
    key = payload.get("key") or ""
    return key if isinstance(key, str) and key else None


def _delete_unlock(ticket: str | None) -> None:
    if not ticket or not isinstance(ticket, str):
        return
    try:
        _ticket_path(ticket).unlink(missing_ok=True)
    except OSError:
        pass


def parse_lock(raw: str | None) -> tuple[str, str] | None:
    s = (raw or "").strip()
    m = LOCK_RE.fullmatch(s)
    if not m:
        return None
    return m.group(1), m.group(2)


def normalize_lock(raw: str | None) -> str:
    parsed = parse_lock(raw)
    if not parsed:
        return ""
    return f"{parsed[0]}-{parsed[1]}"


def _settings(household) -> dict:
    raw = getattr(household, "settings_json", None)
    return dict(raw) if isinstance(raw, dict) else {}


def vault_blob(household) -> dict:
    blob = _settings(household).get("vault")
    return dict(blob) if isinstance(blob, dict) else {}


def vault_enabled(household) -> bool:
    return bool(vault_blob(household).get("enabled") and vault_blob(household).get("salt"))


def vault_hint(household) -> str:
    return (vault_blob(household).get("hint") or "").strip()


def _derive(lock: str, salt: bytes) -> tuple[Fernet, str]:
    material = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=b"family.poweredby.top.vault.v1",
    ).derive(lock.encode("utf-8"))
    key = base64.urlsafe_b64encode(material).decode("ascii")
    return Fernet(key.encode("ascii")), key


def set_vault(household: Household, lock: str, *, commit: bool = True) -> tuple[bool, str]:
    from app.builddb.builddb import db

    parsed = parse_lock(lock)
    if not parsed:
        return False, FORMAT_HINT
    if vault_enabled(household):
        return False, "This household already has a lock. We cannot replace it from here."
    salt = os.urandom(16)
    fernet, _key = _derive(normalize_lock(lock), salt)
    settings = _settings(household)
    settings["vault"] = {
        "enabled": True,
        "salt": salt.hex(),
        "check": fernet.encrypt(CHECK_PLAIN).decode("ascii"),
        "hint": f"{parsed[0]}-\u2026",
    }
    household.settings_json = settings
    flag_modified(household, "settings_json")
    if commit:
        db.session.commit()
    return True, "Family lock is on. Write it down. We cannot recover it."


def unlock_vault(household: Household, lock: str) -> tuple[bool, str]:
    from flask import session

    if household is None or not vault_enabled(household):
        return True, ""
    blob = vault_blob(household)
    try:
        salt = bytes.fromhex(blob.get("salt") or "")
    except Exception:
        return False, "This household lock is damaged. Ask a leader."
    phrase = normalize_lock(lock) or (lock or "").strip()
    if not phrase:
        return False, FORMAT_HINT
    fernet, key = _derive(phrase, salt)
    try:
        if fernet.decrypt(blob["check"].encode("ascii")) != CHECK_PLAIN:
            return False, "That lock does not open this household."
    except (InvalidToken, Exception):
        return False, "That lock does not open this household."
    session[SESSION_HID] = int(household.id)
    session[SESSION_KEY] = _save_unlock(int(household.id), key)
    return True, "Household unlocked."


def lock_session() -> None:
    from flask import has_request_context, session

    if not has_request_context():
        return
    _delete_unlock(session.get(SESSION_KEY))
    session.pop(SESSION_HID, None)
    session.pop(SESSION_KEY, None)


def vault_unlocked(household) -> bool:
    if household is None or not vault_enabled(household):
        return True
    from flask import has_request_context, session

    if not has_request_context():
        return False
    try:
        return int(session.get(SESSION_HID) or 0) == int(household.id) and (
            session_fernet() is not None
        )
    except Exception:
        return False


def session_fernet() -> Fernet | None:
    from flask import has_request_context, session

    if not has_request_context():
        return None
    ticket = session.get(SESSION_KEY)
    hid = session.get(SESSION_HID)
    if not ticket or not hid:
        return None
    key = _load_unlock(ticket, int(hid))
    if not key:
        return None
    try:
        return Fernet(key.encode("ascii"))
    except Exception:
        return None
