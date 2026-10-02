"""fos_vault_ views: read-only vault.

Nothing here writes. The list endpoint returns card metadata only — no
passwords, no account numbers — so a routine poll never drags plaintext out
of the vault. Opening one card decrypts it and writes a specific audit row.

Access follows the same rules the vault page uses: never a child, and only
cards this bot may see (its own, the whole household's, or one shared with
it on a live grant). A `fos_bot_` key cannot reach any of this.
"""
from __future__ import annotations

from app.builddb.builddb import db
from app.routes.bot_api import (
    VAULT,
    bot_api_bp,
    limit_arg,
    note_activity,
    offset_arg,
    ok,
    page,
)
from app.utils.bot_api_auth import (
    api_error,
    api_household_id,
    api_scope,
    api_user,
    audit,
    bot_api,
    iso,
)
from app.utils.password_vault import (
    can_use_vault,
    can_view_entry,
    grant_status,
    kind_label,
    kind_one,
    log_vault_access,
    remaining_text,
    site_label,
)


def _card_meta(entry):
    """List shape: enough to pick a card, no secrets."""
    return {
        "id": entry.id,
        "kind": entry.kind,
        "kind_label": kind_label(entry),
        "share_mode": entry.share_mode,
        "created_by": entry.created_by,
        "grants": [
            {"user_id": g.user_id, "status": grant_status(g)}
            for g in (entry.grants or [])
            if grant_status(g) == "live"
        ],
        "updated_at": iso(entry.updated_at),
        "open_url": f"/api/v1/vault/{entry.id}",
    }


def _visible_entries():
    from app.builddb.table_vault_entries import VaultEntry

    user = api_user()
    return api_scope(VaultEntry).order_by(VaultEntry.id.desc())


def _may_see(entry) -> bool:
    user = api_user()
    if entry is None or user is None:
        return False
    if int(getattr(entry, "household_id", 0) or 0) != api_household_id():
        return False
    if not can_use_vault(user):
        return False
    return can_view_entry(entry, user)


@bot_api_bp.route("/vault")
@bot_api(VAULT)
def vault_list():
    user = api_user()
    if not can_use_vault(user):
        return api_error(
            "This bot cannot use the vault. A vault key belongs on a leader or member.",
            403,
            "vault_forbidden",
        )
    rows = [
        e
        for e in _visible_entries().offset(offset_arg()).limit(limit_arg()).all()
        if _may_see(e)
    ]
    return ok({"entries": [_card_meta(e) for e in rows], **page(rows)})


@bot_api_bp.route("/vault/<int:entry_id>")
@bot_api(VAULT)
def vault_get(entry_id):
    from app.builddb.table_vault_entries import VaultEntry
    from app.utils.password_vault import open_fields, two_factor_label

    user = api_user()
    if not can_use_vault(user):
        return api_error(
            "This bot cannot use the vault. A vault key belongs on a leader or member.",
            403,
            "vault_forbidden",
        )
    entry = api_scope(VaultEntry).filter_by(id=entry_id).first()
    if entry is None or not _may_see(entry):
        # A card this bot cannot see and a card that does not exist look the
        # same on purpose.
        audit(
            event="vault.read",
            status=404,
            outcome="not_visible",
            user_id=getattr(user, "id", None),
            scope=VAULT,
            detail={"entry_id": entry_id},
        )
        return api_error("No such vault card in this household.", 404, "not_found")

    fields = open_fields(entry, api_household_id())
    log_vault_access(entry, user, "view")
    db.session.commit()
    audit(
        event="vault.read",
        status=200,
        outcome="revealed",
        user_id=getattr(user, "id", None),
        scope=VAULT,
        detail={"entry_id": entry.id, "kind": entry.kind},
    )
    note_activity(
        "bot.vault.read",
        f"A bot opened the vault card {kind_one(entry)}",
        target_table="vault_entries",
        target_id=entry.id,
    )
    return ok(
        {
            "entry": {
                "id": entry.id,
                "kind": entry.kind,
                "kind_label": kind_label(entry),
                "kind_one": kind_one(entry),
                "share_mode": entry.share_mode,
                "site": site_label(fields.get("url")),
                "two_factor": two_factor_label(fields.get("two_factor")),
                "title": fields.get("title") or "",
                "login": fields.get("login") or "",
                "secret": fields.get("secret") or "",
                "url": fields.get("url") or "",
                "purpose": fields.get("purpose") or "",
                "details": fields.get("details") or "",
                "phone": fields.get("phone") or "",
                "phone_alt": fields.get("phone_alt") or "",
                "account_no": fields.get("account_no") or "",
                "two_factor_detail": fields.get("two_factor_detail") or "",
                "call_info": fields.get("call_info") or "",
                "grants": [
                    {"user_id": g.user_id, "status": grant_status(g), "remaining": remaining_text(g)}
                    for g in (entry.grants or [])
                ],
                "updated_at": iso(entry.updated_at),
            }
        }
    )