"""Platform outbound mail. Console (laptop log) or SMTP. Secrets never printed."""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from app.utils.platform_settings import get_setting

# cPanel lists these next to SMTP. They talk to Dovecot (receive), not send.
INBOUND_MAIL_PORTS = frozenset({110, 143, 993, 995})


def normalize_smtp_port_enc(port, enc: str) -> tuple[int, str, str | None]:
    """Return (port, enc, warning). Fixes the usual 995/993 mixup."""
    try:
        port = int(port or 587)
    except Exception:
        port = 587
    enc = (enc or "tls").strip().lower()
    if enc not in ("tls", "ssl", "none"):
        enc = "tls"
    if port in INBOUND_MAIL_PORTS:
        return (
            465,
            "ssl",
            f"Port {port} is for receiving mail (IMAP/POP3), not sending. Switched to 465 SSL.",
        )
    if port == 465 and enc != "ssl":
        return 465, "ssl", "Port 465 uses SSL, not STARTTLS."
    if port == 587 and enc == "ssl":
        return 587, "tls", "Port 587 uses STARTTLS. Use 465 if you want SSL."
    return port, enc, None


def explain_smtp_failure(exc, port: int) -> str:
    text = str(exc or "")
    lowered = text.lower()
    if port in INBOUND_MAIL_PORTS or "dovecot" in lowered:
        return (
            "That host answered as a mailbox (IMAP/POP3), not SMTP. "
            "Use port 465 with SSL, or 587 with STARTTLS."
        )
    return f"SMTP failed: {exc}"


def mail_config() -> dict:
    mode = (get_setting("mail_mode") or os.getenv("MAIL_MODE") or "console").strip().lower()
    if mode not in ("console", "smtp"):
        mode = "console"
    port, enc, _ = normalize_smtp_port_enc(
        get_setting("smtp_port") or "587",
        get_setting("smtp_encryption") or "tls",
    )
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
    ics_method: str = "PUBLISH",
    household=None,
) -> tuple[bool, str]:
    to_email = (to_email or "").strip()
    if not to_email or "@" not in to_email:
        return False, "Need a real To address."
    cfg = None
    if household is not None:
        try:
            from app.utils.household_mail import household_mail_config

            cfg = household_mail_config(household)
        except Exception:
            cfg = None
    if cfg is None:
        cfg = mail_config()
    if not cfg["from_email"] and cfg["mode"] == "smtp":
        return False, "Set a From email first."
    msg = EmailMessage()
    sender = (cfg["from_email"] or "family@localhost").strip()
    if cfg["from_name"]:
        msg["From"] = f"{cfg['from_name']} <{sender}>"
    else:
        msg["From"] = sender
    msg["To"] = to_email
    msg["Subject"] = subject or "(no subject)"
    if cfg["reply_to"]:
        msg["Reply-To"] = cfg["reply_to"]
    domain = sender.rsplit("@", 1)[-1] if "@" in sender else None
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=domain)
    msg.set_content(body or "")
    if ics:
        raw = ics if isinstance(ics, (bytes, bytearray)) else str(ics).encode("utf-8")
        method = (ics_method or "PUBLISH").strip().upper()
        if method not in ("PUBLISH", "REQUEST", "CANCEL"):
            method = "PUBLISH"
        try:
            msg.add_alternative(
                raw.decode("utf-8"),
                subtype="calendar",
            )
            alt = msg.get_payload()[-1]
            alt.set_param("method", method)
            alt.set_param("charset", "UTF-8")
        except Exception:
            pass
        msg.add_attachment(
            raw,
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
        return (
            False,
            "Not sent to the inbox. Email mode is Console (server log only). "
            "Switch to SMTP (real send) and use port 465 SSL or 587 STARTTLS.",
        )

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
            refused = server.send_message(msg, from_addr=sender, to_addrs=[to_email])
        finally:
            try:
                server.quit()
            except Exception:
                pass
        if refused:
            why = refused.get(to_email) or next(iter(refused.values()), refused)
            return False, f"SMTP accepted the connection but refused {to_email}: {why}"
        return (
            True,
            f"Mail server accepted the message for {to_email}. "
            "That is not the inbox — check spam. If nothing arrives, the From domain "
            "needs SPF (and MX) in DNS.",
        )
    except Exception as exc:
        return False, explain_smtp_failure(exc, cfg["smtp_port"])
