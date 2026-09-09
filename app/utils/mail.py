"""Platform outbound mail. Console (laptop log) or SMTP. Secrets never printed."""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage

from app.utils.platform_settings import get_setting


def mail_config() -> dict:
    mode = (get_setting("mail_mode") or os.getenv("MAIL_MODE") or "console").strip().lower()
    if mode not in ("console", "smtp"):
        mode = "console"
    port_raw = get_setting("smtp_port") or "587"
    try:
        port = int(port_raw)
    except Exception:
        port = 587
    enc = (get_setting("smtp_encryption") or "tls").strip().lower()
    if enc not in ("tls", "ssl", "none"):
        enc = "tls"
    from_email = get_setting("mail_from_email")
    return {
        "mode": mode,
        "from_name": get_setting("mail_from_name") or "Family OS",
        "from_email": from_email,
        "reply_to": get_setting("mail_reply_to"),
        "smtp_host": get_setting("smtp_host"),
        "smtp_port": port,
        "smtp_encryption": enc,
        "smtp_username": get_setting("smtp_username"),
        "smtp_password": get_setting("smtp_password"),
        "ready": mode == "console" or bool(get_setting("smtp_host") and from_email),
    }


def send_mail(
    to_email: str,
    subject: str,
    body: str,
    ics: bytes | None = None,
    ics_name: str = "reminder.ics",
) -> tuple[bool, str]:
    to_email = (to_email or "").strip()
    if not to_email or "@" not in to_email:
        return False, "Need a real To address."
    cfg = mail_config()
    if not cfg["from_email"] and cfg["mode"] == "smtp":
        return False, "Set a From email first."
    msg = EmailMessage()
    sender = cfg["from_email"] or "family@localhost"
    if cfg["from_name"]:
        msg["From"] = f"{cfg['from_name']} <{sender}>"
    else:
        msg["From"] = sender
    msg["To"] = to_email
    msg["Subject"] = subject or "(no subject)"
    if cfg["reply_to"]:
        msg["Reply-To"] = cfg["reply_to"]
    msg.set_content(body or "")
    if ics:
        msg.add_attachment(
            ics,
            maintype="text",
            subtype="calendar",
            filename=ics_name,
        )

    if cfg["mode"] == "console":
        print("----- Family OS mail (console) -----", flush=True)
        print(f"To: {to_email}", flush=True)
        print(f"Subject: {msg['Subject']}", flush=True)
        print(body or "", flush=True)
        print("----- end mail -----", flush=True)
        return True, "Logged to console (laptop mode)."

    host = cfg["smtp_host"]
    if not host:
        return False, "SMTP host is empty."
    try:
        if cfg["smtp_encryption"] == "ssl":
            context = ssl.create_default_context()
            server = smtplib.SMTP_SSL(host, cfg["smtp_port"], timeout=20, context=context)
        else:
            server = smtplib.SMTP(host, cfg["smtp_port"], timeout=20)
        try:
            server.ehlo()
            if cfg["smtp_encryption"] == "tls":
                context = ssl.create_default_context()
                server.starttls(context=context)
                server.ehlo()
            if cfg["smtp_username"]:
                server.login(cfg["smtp_username"], cfg["smtp_password"] or "")
            server.send_message(msg)
        finally:
            try:
                server.quit()
            except Exception:
                pass
        return True, f"Sent to {to_email}."
    except Exception as exc:
        return False, f"SMTP failed: {exc}"
