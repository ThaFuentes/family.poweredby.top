"""Local-only Ask replies for vault lookup; vault credentials never reach an AI model."""
from __future__ import annotations

import re

_VAULT_MENTION = re.compile(r"\b(?:vault|vault card)\b", re.I)
_CREDENTIAL_FIELD = re.compile(
    r"\b(?:passwords?|passcodes?|pass\s*phrases?|credentials?|logins?|usernames?|"
    r"account\s+numbers?|2fa|two[- ]factor|verification\s+codes?|pins?)\b",
    re.I,
)
_VALUE_REQUEST = re.compile(
    r"\b(?:what(?:'s|\s+is)?|show|tell\s+me|give\s+me|get|find|retrieve|look\s+up|"
    r"open|check|copy|read)\b.{0,70}\b(?:password|passcode|pass\s*phrase|secret|"
    r"credential|login|username|account\s+number|2fa|two[- ]factor|verification\s+code|pin)\b"
    r"|\b(?:password|passcode|pass\s*phrase|secret|credential|login|username|account\s+number|"
    r"2fa|two[- ]factor|verification\s+code|pin)\b.{0,50}\b(?:for|on|to|of)\b",
    re.I,
)
_RESET_HELP = re.compile(
    r"\b(?:how\s+(?:do|can|to)|help\s+me|steps?\s+to)\b.{0,70}\b(?:reset|change|update|"
    r"recover|forgot|forget|create|choose|make)\b.{0,50}\b(?:password|passcode|login|account)\b"
    r"|\b(?:reset|change|update|recover|forgot|forget|create|choose|make)\b.{0,50}"
    r"\b(?:password|passcode|login|account)\b",
    re.I,
)
_SECRET_TOKEN = re.compile(r"^[A-Za-z0-9!@#$%^&*()_+\-=\[\]{};':\",./?]{10,128}$")
_SECRET_TARGET = re.compile(
    r"\b(?:my|our|their)\b.{0,35}\b(?:password|passcode|pass\s*phrase|secret|credential|"
    r"login|username|account\s+number|2fa|two[- ]factor|verification\s+code|pin)\b"
    r"|\b(?:password|passcode|pass\s*phrase|secret|credential|login|username|account\s+number|"
    r"2fa|two[- ]factor|verification\s+code|pin)\b.{0,35}\b(?:for|on|to|of)\s+"
    r"[A-Za-z0-9][A-Za-z0-9 ._'-]{1,40}"
    r"|\b[A-Za-z][A-Za-z0-9 ._'-]{1,40}\s+(?:password|passcode|login|username|PIN)\b",
    re.I,
)
_PASSWORD_INTENT = re.compile(r"\b(?:password|passcode|pass\s*phrase|secret|credential)\b", re.I)
_TWO_FACTOR_INTENT = re.compile(r"\b(?:2fa|two[- ]factor|verification\s+code)\b", re.I)
_PIN_INTENT = re.compile(r"\bpin\b", re.I)
_LOGIN_INTENT = re.compile(r"\b(?:login|username|user\s*name|email)\b", re.I)
_ACCOUNT_INTENT = re.compile(r"\baccount\s+number\b", re.I)
_WRITE_INTENT = re.compile(r"\b(?:add|create|save|store|update|change|edit|delete|remove)\b", re.I)
_SAVE_SECRET = re.compile(
    r"\b(?:my|our|their)\b.{0,30}\b(?:password|passcode|pass\s*phrase|login|username|pin)\b"
    r".{0,50}\b(?:is|=|:|equals)\b|\b(?:password|passcode|pass\s*phrase|pin)\s*(?:is|=|:)\s*\S+",
    re.I,
)
_LIST_INTENT = re.compile(
    r"^\s*(?:/?(?:list|show|open)\s*(?:the\s+)?(?:vault|cards|passwords?|logins?)?|"
    r"what(?:'s|\s+is)?\s+in\s+(?:the\s+)?vault|/?vault)\s*[.!?]*\s*$",
    re.I,
)
_STOP_WORDS = {
    "a", "an", "and", "are", "can", "card", "cards", "could", "do", "does",
    "for", "give", "have", "i", "in", "is", "it", "me", "my", "of", "on",
    "open", "our", "please", "show", "tell", "the", "their", "this", "to",
    "vault", "want", "we", "what", "whats", "which", "who", "would", "you",
    "password", "passwords", "passcode", "passcodes", "login", "logins", "username",
    "usernames", "credentials", "credential", "secret", "secrets", "account", "number",
    "details", "code", "codes", "pin", "2fa", "factor", "two", "verification",
    "unlock", "list", "all",
}


def is_vault_request(text: str, room: str = "house") -> bool:
    """Intercept actual stored-credential lookups, not general password questions."""
    raw = (text or "").strip()
    token_only = bool(
        _SECRET_TOKEN.fullmatch(raw)
        and re.search(r"[A-Za-z]", raw)
        and re.search(r"\d", raw)
    )
    if (room or "").strip().lower() == "vault" or token_only:
        return True
    if _VAULT_MENTION.search(raw) or _SAVE_SECRET.search(raw):
        return True
    if _RESET_HELP.search(raw) or re.search(r"\b(?:good|strong|secure|safe)\s+(?:password|passcode)\b|\bwhat\s+makes?\b", raw, re.I):
        return False
    if re.search(r"\b(?:what|which)\b.{0,40}\b(?:my|our|their)\b.{0,30}\b(?:password|passcode|pass\s*phrase|login|username|pin)\b", raw, re.I):
        return True
    if not _CREDENTIAL_FIELD.search(raw):
        return False
    return bool(_VALUE_REQUEST.search(raw) and _SECRET_TARGET.search(raw))


def _volatile(say: str, *, locked: bool = False, redirect_url: str = "") -> dict:
    payload = {
        "ok": True,
        "say": say,
        "did": [],
        "vault_locked": locked,
        "volatile": True,
        "sensitive": True,
        "clear_history": True,
    }
    if redirect_url:
        payload["redirect_url"] = redirect_url
    return payload


def _target(text: str) -> str:
    """Extract the card/service name from an explicit credential request."""
    normalized = re.sub(r"['’]s\b", "", (text or "").lower())
    normalized = re.sub(r"\b(?:what(?:'s|\s+is)?|show|tell\s+me|give\s+me|get|find|retrieve|look\s+up|open|check|copy|read)\b", " ", normalized)
    normalized = re.sub(
        r"\b(?:my|our|their|the|password|passcode|pass\s*phrase|secret|credential|login|username|"
        r"account\s+number|2fa|two[- ]factor|verification\s+code|pin|vault|vault\s+card|please|"
        r"is|are|for|on|to|of|what|whats|do|does|can|you)\b",
        " ",
        normalized,
    )
    words = re.findall(r"[\w@.-]+", normalized)
    return " ".join(word for word in words if len(word) > 1 and word not in _STOP_WORDS)[:120]


def local_vault_say(text: str, room: str = "house", *, has_photo: bool = False) -> dict | None:
    """Handle vault requests locally, returning a volatile response or None.

    Requests in the Vault room and explicit credential requests are intercepted
    before any AI call. Secrets are opened only after app-login reauthentication.
    """
    raw = (text or "").strip()
    is_vault_room = (room or "").strip().lower() == "vault"
    if not raw and not is_vault_room:
        return None
    if not is_vault_request(raw, room):
        return None

    # Drop old vault-room turns written by prior versions before sensitive turns
    # were marked volatile. Never persist the current vault request or its reply.
    from app.utils.ask import _vault_guard, clear_history, tool_vault_list, tool_vault_open

    clear_history(room)
    if room != "vault":
        clear_history("vault")
    if has_photo:
        from app.utils.ask_photo import clear_ask_photo

        clear_ask_photo()
        return _volatile("For safety, send a photo in a non-vault Ask room.")

    blocked = _vault_guard()
    if blocked:
        error = str(blocked.get("error") or "")
        if blocked.get("need") == "vault_unlock" or "locked" in error.lower():
            try:
                from flask import session

                session["ask_resume_vault"] = True
            except Exception:
                pass
            from flask import url_for

            try:
                destination = url_for("vault.index", next="/ask/vault")
            except Exception:
                destination = "/vault/?next=%2Fask%2Fvault"
            return _volatile(
                "Opening the vault so you can sign in there. Do not enter your sign-in details in chat.",
                locked=True,
                redirect_url=destination,
            )
        return _volatile(error or "You cannot use the vault from this login.")

    if _SAVE_SECRET.search(raw):
        return _volatile("I won’t repeat or save a password pasted into chat. Add it directly on the vault page: /vault/")
    if _WRITE_INTENT.search(raw):
        return _volatile("For safety, add or change vault cards on the vault page, not in chat. /vault/")
    try:
        from flask import session

        session.pop("ask_resume_vault", None)
    except Exception:
        pass

    query = _target(raw)
    wants_list = bool(_LIST_INTENT.fullmatch(raw)) or (
        is_vault_room and not query and not re.search(r"\b(?:my|our|their)\b.{0,25}\b(?:password|passcode|login|username|pin)\b", raw, re.I)
    ) or bool(
        re.search(r"\b(?:list|show|what|which)\b.{0,30}\b(?:all\s+)?(?:vault|passwords?|logins?|cards)\b", raw, re.I)
        and not _CREDENTIAL_FIELD.search(raw)
    )
    if wants_list or (is_vault_room and _LIST_INTENT.fullmatch(raw)):
        query = ""
    elif not query and re.search(r"\b(?:my|our|their)\b.{0,25}\b(?:password|passcode|login|username|pin)\b", raw, re.I):
        return _volatile("Which vault card do you mean? Name the service or card title. /vault/")
    if wants_list:
        result = tool_vault_list("")
        if not result.get("ok", True):
            return _volatile(str(result.get("error") or "I couldn’t open the vault. /vault/"))
        entries = result.get("entries") or []
        if not entries:
            return _volatile("No vault cards are visible to you. /vault/")
        lines = [
            "· " + str(entry.get("title") or "Vault card")
            + (" · " + str(entry.get("site")) if entry.get("site") else "")
            + (" · " + str(entry.get("href")) if entry.get("href") else "")
            for entry in entries
        ]
        return _volatile("Vault cards:\n" + "\n".join(lines) + "\n/vault/")

    if not query:
        return _volatile("Name the vault card you want me to look up. /vault/")
    result = tool_vault_list(query)
    if not result.get("ok", True):
        return _volatile(str(result.get("error") or "I couldn’t open the vault. /vault/"))
    entries = result.get("entries") or []
    if not entries:
        return _volatile(f"I couldn’t find a vault card matching “{query}”. /vault/")
    if len(entries) > 1:
        names = ", ".join(str(row.get("title") or "Untitled") for row in entries[:8])
        return _volatile(f"Which vault card do you mean: {names}? /vault/")

    card = tool_vault_open(entries[0].get("id"))
    if not card.get("ok"):
        return _volatile(str(card.get("error") or "I couldn’t open that vault card. /vault/"))

    title = str(card.get("title") or entries[0].get("title") or "Vault card")
    href = str(card.get("href") or entries[0].get("href") or "/vault/")
    lines = [f"{title} · {href}"]
    if _LOGIN_INTENT.search(raw) and card.get("login"):
        lines.append("Login: " + str(card["login"]))
    if _ACCOUNT_INTENT.search(raw) and card.get("account_no"):
        lines.append("Account number: " + str(card["account_no"]))
    if _PASSWORD_INTENT.search(raw) or _PIN_INTENT.search(raw):
        secret = str(card.get("secret") or "")
        lines.append("Password / secret: " + secret if secret else "No password is saved on this card.")
    if _TWO_FACTOR_INTENT.search(raw):
        method = str(card.get("two_factor") or "")
        detail = str(card.get("two_factor_detail") or "")
        lines.append(
            "Two-factor method: " + "; ".join(part for part in (method, detail) if part)
            if method or detail else "No two-factor method is saved on this card."
        )
    if len(lines) == 1:
        lines.append("Ask for the login or password if you want that value, or open the card on the vault page.")
    return _volatile("\n".join(lines))
