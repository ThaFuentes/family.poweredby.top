"""Stash a just-minted key so the next page can show a copy window."""

ISSUED_SESSION = "family_issued_key"


def stash_issued_key(code: str, kind: str, hint: str = "", extra: dict | None = None) -> None:
    from flask import session

    blob = {
        "code": (code or "").strip(),
        "kind": kind or "Key",
        "hint": hint or "",
    }
    if isinstance(extra, dict):
        blob["extra"] = extra
    session[ISSUED_SESSION] = blob


def pop_issued_key() -> dict | None:
    from flask import session

    blob = session.pop(ISSUED_SESSION, None)
    if not isinstance(blob, dict) or not blob.get("code"):
        return None
    return blob
