"""Optional per-household data lock.

Leaders may set a memorable master key at start: a word, a dash, then their
secret — example FAMOS-ourphrase. We never store the phrase. Salt + a check
token live on the household. Session holds the derived Fernet while unlocked.
"""
from __future__ import annotations

import base64
import os
import re
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
    session[SESSION_KEY] = key
    return True, "Household unlocked."


def lock_session() -> None:
    from flask import has_request_context, session

    if not has_request_context():
        return
    session.pop(SESSION_HID, None)
    session.pop(SESSION_KEY, None)


def vault_unlocked(household) -> bool:
    if household is None or not vault_enabled(household):
        return True
    from flask import has_request_context, session

    if not has_request_context():
        return False
    try:
        return int(session.get(SESSION_HID) or 0) == int(household.id) and bool(
            session.get(SESSION_KEY)
        )
    except Exception:
        return False


def session_fernet() -> Fernet | None:
    from flask import has_request_context, session

    if not has_request_context():
        return None
    raw = session.get(SESSION_KEY)
    hid = session.get(SESSION_HID)
    if not raw or not hid:
        return None
    try:
        key = raw.encode("ascii") if isinstance(raw, str) else raw
        return Fernet(key)
    except Exception:
        return None
