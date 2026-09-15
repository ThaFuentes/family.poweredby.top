"""Per-household outbound mail. Falls back to the platform SMTP identity."""
from __future__ import annotations

from sqlalchemy.orm.attributes import flag_modified

from app.utils.crypto import decrypt_text, encrypt_text, looks_encrypted
from app.utils.mail import normalize_smtp_port_enc
from app.utils.platform_settings import mask_secret

MAIL_KEYS = (
    "from_name",
    "from_email",
    "reply_to",
    "smtp_host",
    "smtp_port",
    "smtp_encryption",
    "smtp_username",
)


def _settings(household) -> dict:
    raw = getattr(household, "settings_json", None)
    return dict(raw) if isinstance(raw, dict) else {}


def mail_blob(household) -> dict:
    blob = _settings(household).get("mail")
    return dict(blob) if isinstance(blob, dict) else {}


def _decrypt_pass(stored: str) -> str:
    raw = (stored or "").strip()
    if not raw:
        return ""
    if looks_encrypted(raw):
        return (decrypt_text(raw) or "").strip()
    return raw


def household_mail_config(household) -> dict | None:
    """Ready SMTP config for this house, or None to use the platform mailbox."""
    if household is None:
        return None
    blob = mail_blob(household)
    if not blob.get("enabled"):
        return None
    host = (blob.get("smtp_host") or "").strip()
    from_email = (blob.get("from_email") or "").strip()
    if not host or not from_email:
        return None
    port, enc, _ = normalize_smtp_port_enc(
        blob.get("smtp_port") or 587,
        blob.get("smtp_encryption") or "tls",
    )
    return {
        "mode": "smtp",
        "from_name": (blob.get("from_name") or "").strip() or "Family OS",
        "from_email": from_email,
        "reply_to": (blob.get("reply_to") or "").strip(),
        "smtp_host": host,
        "smtp_port": port,
        "smtp_encryption": enc,
        "smtp_username": (blob.get("smtp_username") or "").strip(),
        "smtp_password": _decrypt_pass(blob.get("smtp_password") or ""),
        "ready": True,
        "source": "household",
    }


def public_mail_config(household) -> dict:
    blob = mail_blob(household)
    pwd = _decrypt_pass(blob.get("smtp_password") or "")
    port, enc, _ = normalize_smtp_port_enc(
        blob.get("smtp_port") or 587,
        blob.get("smtp_encryption") or "tls",
    )
    enabled = bool(blob.get("enabled"))
    host = (blob.get("smtp_host") or "").strip()
    from_email = (blob.get("from_email") or "").strip()
    return {
        "enabled": enabled,
        "from_name": (blob.get("from_name") or "").strip(),
        "from_email": from_email,
        "reply_to": (blob.get("reply_to") or "").strip(),
        "smtp_host": host,
        "smtp_port": port,
        "smtp_encryption": enc,
        "smtp_username": (blob.get("smtp_username") or "").strip(),
        "smtp_password_hint": mask_secret(pwd),
        "has_password": bool(pwd),
        "ready": enabled and bool(host and from_email),
    }


def save_household_mail(
    household,
    *,
    enabled: bool,
    from_name: str = "",
    from_email: str = "",
    reply_to: str = "",
    smtp_host: str = "",
    smtp_port: str | int = 587,
    smtp_encryption: str = "tls",
    smtp_username: str = "",
    smtp_password: str = "",
    clear_password: bool = False,
) -> dict:
    from app.builddb.builddb import db

    settings = _settings(household)
    prev = dict(settings.get("mail") or {}) if isinstance(settings.get("mail"), dict) else {}
    port, enc, port_warning = normalize_smtp_port_enc(smtp_port, smtp_encryption)
    stored_pass = prev.get("smtp_password") or ""
    if clear_password:
        stored_pass = ""
    elif (smtp_password or "").strip():
        stored_pass = encrypt_text((smtp_password or "").strip()) or ""
    settings["mail"] = {
        "enabled": bool(enabled),
        "from_name": (from_name or "").strip()[:80],
        "from_email": (from_email or "").strip()[:120],
        "reply_to": (reply_to or "").strip()[:120],
        "smtp_host": (smtp_host or "").strip()[:120],
        "smtp_port": port,
        "smtp_encryption": enc,
        "smtp_username": (smtp_username or "").strip()[:120],
        "smtp_password": stored_pass,
    }
    household.settings_json = settings
    flag_modified(household, "settings_json")
    db.session.commit()
    out = public_mail_config(household)
    out["smtp_fix"] = port_warning
    return out


def random_login_password() -> str:
    import secrets

    return "Fam-" + secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:8]


def invite_email_body(
    *,
    household,
    code: str,
    role: str,
    register_url: str,
    login_url: str,
    username: str | None = None,
    password: str | None = None,
    lock: str | None = None,
    person_name: str = "",
) -> str:
    handle = (getattr(household, "handle", None) or "").strip()
    house = (getattr(household, "name", None) or "your household").strip()
    who = (person_name or "").strip() or "there"
    lines = [
        f"Hi {who},",
        "",
        f"You were invited into {house} on Family OS.",
        "",
    ]
    if username and password:
        lines += [
            "Your login is already made:",
            f"  Household handle: {handle or '(ask the person who invited you)'}",
            f"  Username: {username}",
            f"  Password: {password}",
            "",
            f"Sign in: {login_url}",
            "Change the password after you get in (Look).",
            "",
        ]
    lines += [
        "Family key (join this household if you still need to register):",
        f"  {code}",
        f"  Role: {role}",
        "",
        f"Join page: {register_url}",
        "",
    ]
    if lock:
        lines += [
            "Household lock (opens notes and photos for this family):",
            f"  {lock}",
            "Keep this off shared computers. The site cannot recover it.",
            "",
        ]
    lines.append("If you did not expect this, ignore the email.")
    return "\n".join(lines)


def added_person_email_body(
    *,
    household,
    login_url: str,
    username: str,
    password: str,
    person_name: str = "",
    calendar_label: str = "",
) -> str:
    handle = (getattr(household, "handle", None) or "").strip()
    house = (getattr(household, "name", None) or "your household").strip()
    who = (person_name or "").strip() or "there"
    lines = [
        f"Hi {who},",
        "",
        f"You're on {house} in Family OS. No key to type — a login was made for you.",
        "",
        f"  Household handle: {handle or '(ask whoever added you)'}",
        f"  Username: {username}",
        f"  Password: {password}",
        "",
        f"Sign in: {login_url}",
        "Change the password after you get in (Look).",
        "",
    ]
    if calendar_label:
        lines += [
            f"Due dates go to {calendar_label}.",
            "",
        ]
    lines.append("If you did not expect this, ignore the email.")
    return "\n".join(lines)
