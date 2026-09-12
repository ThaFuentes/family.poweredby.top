"""Friends-and-family gate.

Two different keys. They are not interchangeable.

- Family key (FAM-…): join a specific household.
- Service key (SRV-…): get onto Family OS at all. Stops random signups.
Trusted emails skip the service key. A family key is enough to join that household.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.builddb.builddb import db
from app.builddb.table_households import Household
from app.builddb.table_invites import Invite
from app.builddb.table_service_passes import ServicePass
from app.builddb.table_trusted_emails import TrustedEmail


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalize_code(raw: str | None) -> str:
    return (raw or "").strip().upper().replace(" ", "").replace("—", "-")


def family_code_variants(code: str) -> list[str]:
    c = normalize_code(code)
    if not c:
        return []
    out = [c]
    if c.startswith("FAM-"):
        out.append(c[4:])
    elif not c.startswith("SRV-"):
        out.append("FAM-" + c)
    return out


def service_code_variants(code: str) -> list[str]:
    c = normalize_code(code)
    if not c:
        return []
    out = [c]
    if c.startswith("SRV-"):
        return out
    if not c.startswith("FAM-"):
        out.append("SRV-" + c)
    return out


def household_count() -> int:
    try:
        return int(Household.query.count() or 0)
    except Exception:
        return 0


def bootstrap_open() -> bool:
    """First household on a fresh install does not need a service key."""
    return household_count() == 0


def find_family_invite(code: str) -> Invite | None:
    for variant in family_code_variants(code):
        row = Invite.query.filter_by(code=variant).first()
        if row:
            return row
    return None


def find_service_pass(code: str) -> ServicePass | None:
    for variant in service_code_variants(code):
        row = ServicePass.query.filter_by(code=variant).first()
        if row:
            return row
    return None


def family_invite_ok(invite: Invite | None) -> tuple[bool, str]:
    if invite is None:
        return False, "That Family key is not valid."
    if getattr(invite, "revoked_at", None):
        return False, "That Family key was revoked."
    if invite.used_at:
        return False, "That Family key was already used."
    if invite.expires_at and invite.expires_at < _utcnow():
        return False, "That Family key has expired. Ask your household for a new one."
    h = Household.query.get(invite.household_id)
    if h is None or not bool(h.is_active):
        return False, "That household is not accepting people right now."
    return True, ""


def service_pass_ok(row: ServicePass | None) -> tuple[bool, str]:
    if row is None:
        return False, "That Service key is not valid."
    if row.revoked_at:
        return False, "That Service key was revoked."
    if row.expires_at and row.expires_at < _utcnow():
        return False, "That Service key has expired. Ask a friend already on Family OS for a new one."
    max_uses = int(row.max_uses or 1)
    if int(row.use_count or 0) >= max_uses:
        return False, "That Service key has no uses left."
    return True, ""


def email_is_trusted(email: str | None) -> bool:
    addr = (email or "").strip().lower()
    if not addr or "@" not in addr:
        return False
    return TrustedEmail.query.filter_by(email=addr).first() is not None


def can_enter_service(*, email: str | None, service_key: str, family_key: str) -> tuple[bool, str, dict]:
    """May this person create an account on Family OS?"""
    if family_key:
        family = find_family_invite(family_key)
        ok, err = family_invite_ok(family)
        if not ok:
            return False, err, {}
        return True, "family", {"invite": family, "pass": None}

    if bootstrap_open():
        return True, "bootstrap", {"invite": None, "pass": None}

    if email_is_trusted(email):
        return True, "trusted_email", {"invite": None, "pass": None}

    if service_key:
        row = find_service_pass(service_key)
        ok, err = service_pass_ok(row)
        if ok:
            return True, "service", {"invite": None, "pass": row}
        return False, err, {}

    return (
        False,
        "Family OS is friends and family only. You need a Service key to get on the site, a Family key to join a household, or an email already on the trusted list.",
        {},
    )


def consume_service_pass(row: ServicePass | None) -> None:
    if row is None:
        return
    row.use_count = int(row.use_count or 0) + 1
    row.last_used_at = _utcnow()
    db.session.add(row)


def mint_service_pass(
    *,
    created_by=None,
    household_id=None,
    label: str = "",
    max_uses: int = 1,
    days: int = 14,
) -> ServicePass:
    try:
        uses = max(1, min(int(max_uses or 1), 50))
    except Exception:
        uses = 1
    try:
        life = max(1, min(int(days or 14), 365))
    except Exception:
        life = 14
    row = ServicePass(
        code=ServicePass.new_code(),
        created_by=created_by,
        household_id=household_id,
        label=(label or "").strip()[:120] or None,
        max_uses=uses,
        use_count=0,
        expires_at=_utcnow() + timedelta(days=life),
    )
    db.session.add(row)
    db.session.commit()
    return row


def add_trusted_email(*, email: str, added_by=None, household_id=None, note: str = "") -> tuple[bool, str, TrustedEmail | None]:
    addr = (email or "").strip().lower()
    if "@" not in addr or "." not in addr.split("@")[-1]:
        return False, "That does not look like an email.", None
    existing = TrustedEmail.query.filter_by(email=addr).first()
    if existing:
        return True, "That email was already trusted.", existing
    row = TrustedEmail(
        email=addr,
        added_by=added_by,
        household_id=household_id,
        note=(note or "").strip()[:200] or None,
    )
    db.session.add(row)
    db.session.commit()
    return True, f"{addr} can join Family OS anytime — still needs a Family key to enter a household.", row


def revoke_service_pass(row: ServicePass) -> None:
    row.revoked_at = _utcnow()
    db.session.commit()


def revoke_family_invite(row: Invite) -> None:
    row.revoked_at = _utcnow()
    db.session.commit()


def revoke_key_by_code(raw: str) -> tuple[bool, str, str]:
    """Kill a SRV- or FAM- key from its code. For abuse. Returns (ok, message, kind)."""
    code = normalize_code(raw)
    if not code:
        return False, "Paste a key.", ""
    fam = find_family_invite(code)
    if fam is not None:
        if getattr(fam, "revoked_at", None):
            return True, f"{fam.code} was already revoked.", "family"
        if fam.used_at:
            return False, f"{fam.code} was already used. Revoke does not undo a signup.", "family"
        revoke_family_invite(fam)
        return True, f"{fam.code} revoked.", "family"
    srv = find_service_pass(code)
    if srv is not None:
        if srv.revoked_at:
            return True, f"{srv.code} was already revoked.", "service"
        revoke_service_pass(srv)
        return True, f"{srv.code} revoked.", "service"
    return False, "No key matches that code.", ""
