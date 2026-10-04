"""Maya's permission checklist for Family OS.

Every action Maya's API can take is one permission here, grouped by area,
with a plain-English line for the owner. The owner page and
``GET /api/v1/maya/capabilities`` both read this catalog, and every Maya API
call re-reads the saved state from the database (no cache), so a change on
the owner page takes effect on Maya's very next request.

Normal permissions default ON for Maya. High-risk ones default OFF and can
only be switched on by the owner after re-entering their password (or a
fresh authenticator code).

HARD LIMITS (in code, no checkbox can lift them):
  * Maya can never read or change her own checklist through any write path.
  * Maya can never read or export raw secrets: login/API keys, 2FA secrets,
    password hashes, decrypted vault passwords, SMTP/AI keys.
  * Maya can never change her own role, leader flag, keys, or password.
  * Every Maya write is audit-logged; removals go to the recycle bin.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.builddb.builddb import db

def _p(pid, group, label, detail, *, high=False, implemented=True):
    return {
        "id": pid,
        "group": group,
        "label": label,
        "detail": detail,
        "high_risk": bool(high),
        "default": not high,
        "implemented": bool(implemented),
    }


def _crud(area, group, noun, extra_detail="", *, actions=("read", "create", "edit", "delete", "restore")):
    out = []
    for act in actions:
        if act == "read":
            out.append(_p(f"{area}.read", group, f"See {noun}", f"List and open {noun}. {extra_detail}".strip()))
        elif act == "create":
            out.append(_p(f"{area}.create", group, f"Add {noun}", f"Create new {noun}. Shows in the app as added by Maya."))
        elif act == "edit":
            out.append(_p(f"{area}.edit", group, f"Edit {noun}", f"Change existing {noun}."))
        elif act == "delete":
            out.append(_p(f"{area}.delete", group, f"Remove {noun}", f"Take {noun} out. Nothing is destroyed: it goes to the recycle bin and can be put back."))
        elif act == "restore":
            out.append(_p(f"{area}.restore", group, f"Put back {noun}", f"Restore {noun} from the recycle bin or Happened."))
    return out


CATALOG: list[dict] = []
CATALOG += _crud("inventory", "Inventory", "inventory items", "Groceries and other things in the house, counts, rooms, use-by dates.")
CATALOG += [
    _p("inventory.stock", "Inventory", "Change counts", "Used one, restocked, +/- the count, need more, freezer/fridge. Same buttons as the item page."),
]
CATALOG += _crud("basket", "Basket", "basket lines", "The store list.")
CATALOG += [
    _p("basket.check", "Basket", "Check off / reopen basket lines", "Mark a line got (restocks the matching item) or put it back on the list."),
]
CATALOG += _crud("vehicles", "Vehicles", "vehicles", "Make, model, VIN, plate, oil info.")
CATALOG += [
    _p("vehicles.reading", "Vehicles", "Update miles / hours", "Set the odometer on a vehicle or the hour meter on a tool. Writes a log row like the app does."),
]
CATALOG += _crud("tools", "Tools", "tools", "Tools and equipment with oil and hours.")
CATALOG += _crud("house", "House file", "house things", "Appliances, HVAC, pool, coop and the rest of the house file.")
CATALOG += _crud("logs", "Maintenance & logs", "log entries", "Fill-ups, repairs, oil changes, codes, trips and notes on a vehicle, tool or house.",
                 actions=("read", "create", "delete", "restore"))
CATALOG += _crud("parts", "Parts & equipment", "parts", "Parts installed on a vehicle or house slot.",
                 actions=("read", "create", "edit"))
CATALOG += [
    _p("parts.retire", "Parts & equipment", "Take parts off", "Mark a part removed/retired. A parent can put it back on Happened."),
    _p("parts.restore", "Parts & equipment", "Put parts back on", "Undo a part being taken off."),
]
CATALOG += _crud("reminders", "Reminders & calendar", "reminders", "Due list and what feeds the household calendar (the private calendar link itself is never shown).")
CATALOG += [
    _p("reminders.complete", "Reminders & calendar", "Mark reminders done / reopen", "Check a reminder off or open it again."),
]
CATALOG += _crud("notes", "Notes", "notes", "Household notes and Maya's own notes. Personal notes of other people stay private.")
CATALOG += [
    _p("files.read", "Files & photos", "Open files and photos", "Download note attachments, item photos and receipts."),
    _p("files.upload", "Files & photos", "Upload files and photos", "Attach photos/PDFs to notes and photos/receipts to items. Type and size are checked, names cleaned, photo location data (EXIF) stripped."),
    _p("files.replace", "Files & photos", "Replace files and photos", "Swap a file for a new one. The old version is kept outside the website folder and can be restored."),
    _p("files.delete", "Files & photos", "Remove files and photos", "Take a file off. The bytes are archived outside the website folder and can be restored."),
    _p("files.restore", "Files & photos", "Restore old file versions", "Put a replaced or removed file back."),
]
CATALOG += _crud("records", "Records & cases", "records", "Notices, tickets, letters (the Records page).")
CATALOG += [
    _p("cases.read", "Records & cases", "See cases", "Cases and their follow-ups."),
    _p("cases.create", "Records & cases", "Open cases", "Open a case, attach records to it."),
    _p("cases.edit", "Records & cases", "Edit cases", "Change case title, status, summary; attach/detach records."),
    _p("cases.followup", "Records & cases", "Add case follow-ups", "Notes, emails, links on a case."),
    _p("cases.delete", "Records & cases", "Remove case follow-ups", "Recycle bin, restorable."),
]
CATALOG += [
    _p("activity.read", "Activity log", "See Happened", "The household activity log."),
    _p("activity.undo", "Activity log", "Undo on Happened", "Use the same Put back button a leader has on Happened."),
    _p("trash.read", "Recycle bin", "See the recycle bin", "What was removed, by whom, and when."),
    _p("trash.restore", "Recycle bin", "Restore from the recycle bin", "Put a removed row (and its files) back."),
    _p("search.read", "Search", "Search the house", "The Find page across items, notes and (when allowed) records."),
    _p("people.read", "People", "See household members", "Names, usernames and roles. Never passwords, security inboxes or keys."),
    _p("ask.read", "Ask", "See Maya's own Ask history", "Only her own chat turns."),
]
# ----- high risk: default OFF, owner re-confirms with password / 2FA -----
CATALOG += [
    _p("people.create", "People (high risk)", "Add people", "Add a household member. Not built for the API: a new login shows its password once, and Maya must never see passwords. Use the People page.", high=True, implemented=False),
    _p("people.role", "People (high risk)", "Change roles", "Set someone to admin/member/child. Never Maya's own account, never leader flags.", high=True),
    _p("people.remove", "People (high risk)", "Remove people", "Take a person off People (restorable on Happened). Never Maya, never the last leader.", high=True),
    _p("people.reset_password", "People (high risk)", "Send password resets", "Email someone a reset link (their reset inbox). Maya never sees the link or the password.", high=True),
    _p("settings.household", "Settings (high risk)", "Rename household / rooms", "Household name and room list.", high=True),
    _p("settings.reminders", "Settings (high risk)", "Reminder delivery", "Email / calendar / both for the household.", high=True),
    _p("settings.security", "Settings (high risk)", "Security & mail settings", "Mailbox, AI keys, 2FA policy. Not built for the API: listed so it stays visibly off.", high=True, implemented=False),
    _p("vault.read", "Vault (high risk)", "See vault card names", "Card titles and kinds only. Passwords and account numbers are never sent to Maya.", high=True),
    _p("trash.purge", "Recycle bin (high risk)", "Permanently delete", "Hard delete from the recycle bin. Cannot be undone; the audit row stays.", high=True),
    _p("records.amounts", "Money (high risk)", "Edit amounts on records", "Change the fine/amount field on a record. Family OS takes no payments.", high=True),
]

CATALOG_BY_ID = {p["id"]: p for p in CATALOG}

# Never grantable. Checked in the gate even if a row appears in the DB.
HARD_LIMITS = [
    "Maya cannot open or change this checklist, and cannot pick who Maya is.",
    "Maya cannot read or export raw secrets: login/API keys, 2FA secrets, password hashes, decrypted vault passwords, mail or AI keys, the private calendar link.",
    "Maya cannot change her own role, leader flag, password, 2FA, inboxes, or keys (she can only rotate her own login key with /auth/reset).",
    "Every Maya write is audit-logged (bot_api_audit + Happened). Removals go to the recycle bin; purge needs the high-risk switch.",
]
FORBIDDEN_IDS = frozenset({
    "maya.permissions.edit", "keys.read", "secrets.read", "self.role", "self.password", "vault.secrets",
})


def groups() -> list[dict]:
    """Catalog grouped by area, in catalog order."""
    out: list[dict] = []
    index: dict[str, dict] = {}
    for perm in CATALOG:
        grp = index.get(perm["group"])
        if grp is None:
            grp = {"name": perm["group"], "perms": [], "high_risk": perm["high_risk"]}
            index[perm["group"]] = grp
            out.append(grp)
        grp["perms"].append(perm)
    return out


# ----------------------------------------------------------- Maya identity


def maya_account(household_id: int):
    from app.builddb.table_maya_bot import MayaBotAccount

    if not household_id:
        return None
    return MayaBotAccount.query.filter_by(household_id=int(household_id)).first()


def is_maya(user) -> bool:
    if user is None or not bool(getattr(user, "is_bot", False)):
        return False
    acct = maya_account(getattr(user, "household_id", 0))
    return bool(acct and acct.enabled and int(acct.user_id) == int(user.id))


def set_maya(household_id: int, user, *, by_user) -> tuple[bool, str]:
    from app.builddb.table_maya_bot import MayaBotAccount

    if user is None or not bool(getattr(user, "is_bot", False)):
        return False, "Maya has to be a BOT account."
    if int(user.household_id) != int(household_id):
        return False, "That person is not in this house."
    acct = maya_account(household_id)
    old = int(acct.user_id) if acct else None
    if acct is None:
        acct = MayaBotAccount(household_id=int(household_id), user_id=int(user.id), enabled=True)
        db.session.add(acct)
    acct.user_id = int(user.id)
    acct.enabled = True
    acct.set_by = getattr(by_user, "id", None)
    _log(household_id, user.id, by_user, "maya.account", old is not None, True, False, None)
    return True, f"{user.name or user.username} is Maya now." if old != user.id else "Saved."


# ------------------------------------------------------------- live state


EXPIRY_UNITS = {"hours": 1, "days": 24, "weeks": 24 * 7, "months": 24 * 30}
HIGH_RISK_DEFAULT_EXPIRY = ("hours", 24)
MAX_EXPIRY_HOURS = 24 * 366


def parse_expiry(unit, number, *, now=None):
    """('days', 3) -> UTC datetime. 'none'/blank -> None. Bad input -> ValueError."""
    unit = (str(unit or "")).strip().lower()
    if unit in ("", "none", "never", "no_expiry"):
        return None
    if unit not in EXPIRY_UNITS:
        raise ValueError("Pick hours, days, weeks or months.")
    try:
        n = int(str(number).strip())
    except (TypeError, ValueError):
        raise ValueError("The timer needs a whole number.")
    if n < 1:
        raise ValueError("The timer must be at least 1.")
    hours = min(n * EXPIRY_UNITS[unit], MAX_EXPIRY_HOURS)
    return (now or datetime.utcnow()) + timedelta(hours=hours)


def _expire_row(row, now) -> None:
    """Flip one expired switch off and audit it as auto-expired (caller commits)."""
    row.enabled = False
    old_exp = row.expires_at
    row.expires_at = None
    row.updated_at = now
    perm = CATALOG_BY_ID.get(row.perm) or {}
    _log(row.household_id, row.user_id, None, row.perm, True, False, perm.get("high_risk", False),
         "auto-expired", None)
    from app.builddb.table_household_activity import HouseholdActivity

    db.session.add(HouseholdActivity(
        household_id=int(row.household_id), user_id=None, action="maya.perms.expired",
        summary=f"Maya permission {row.perm} auto-expired",
        target_table="maya_bot_permissions", target_id=int(row.user_id),
        new_json={"perm": row.perm, "expired_at": old_exp.isoformat() if old_exp else None},
        reversible=False,
    ))


def expire_due(now=None) -> int:
    """Cron/lazy cleanup: switch off every expired permission. Returns count."""
    from app.builddb.table_maya_bot import MayaBotPermission

    now = now or datetime.utcnow()
    rows = (MayaBotPermission.query.filter(MayaBotPermission.enabled.is_(True),
                                           MayaBotPermission.expires_at.isnot(None),
                                           MayaBotPermission.expires_at <= now).all())
    for row in rows:
        _expire_row(row, now)
    if rows:
        db.session.commit()
    return len(rows)


def perm_rows(household_id: int, user_id: int) -> dict:
    from app.builddb.table_maya_bot import MayaBotPermission

    return {r.perm: r for r in MayaBotPermission.query.filter_by(
        household_id=int(household_id), user_id=int(user_id)).all()}


def perm_state(household_id: int, user_id: int, *, cleanup: bool = True) -> dict[str, bool]:
    """Live from the DB on every call. Missing row -> catalog default.

    An expired switch is OFF right away; with cleanup=True the row is also
    flipped off and an 'auto-expired' audit line written (lazy cleanup).
    """
    now = datetime.utcnow()
    state = {p["id"]: bool(p["default"]) for p in CATALOG}
    expired = []
    for pid, row in perm_rows(household_id, user_id).items():
        if pid not in state:
            continue
        on = bool(row.enabled)
        if on and row.expires_at is not None and row.expires_at <= now:
            on = False
            expired.append(row)
        state[pid] = on
    for pid, perm in CATALOG_BY_ID.items():
        if not perm["implemented"]:
            state[pid] = False  # no endpoint exists, so it can never be "on"
    if expired and cleanup:
        try:
            for row in expired:
                _expire_row(row, now)
            db.session.commit()
        except Exception as exc:  # the live answer above is already OFF
            db.session.rollback()
            print(f"[maya] lazy expiry failed: {exc}", flush=True)
    return state


def perm_expiry(household_id: int, user_id: int) -> dict:
    """{perm: expires_at datetime} for switches that are on with a timer."""
    now = datetime.utcnow()
    return {pid: r.expires_at for pid, r in perm_rows(household_id, user_id).items()
            if r.enabled and r.expires_at is not None and r.expires_at > now}


def remaining_text(expires_at, now=None) -> str:
    if expires_at is None:
        return "no expiry"
    secs = int((expires_at - (now or datetime.utcnow())).total_seconds())
    if secs <= 0:
        return "expired"
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    if days:
        return f"{days}d {hours}h left"
    if hours:
        return f"{hours}h {mins}m left"
    return f"{max(mins, 1)}m left"


def allowed(user, perm_id: str) -> bool:
    if perm_id in FORBIDDEN_IDS or perm_id not in CATALOG_BY_ID:
        return False
    if not is_maya(user):
        return False
    return bool(perm_state(user.household_id, user.id).get(perm_id))


def _log(hid, maya_id, owner, perm, old, new, high, confirmed_with, ip=None):
    from app.builddb.table_maya_bot import MayaBotPermLog

    db.session.add(
        MayaBotPermLog(
            household_id=int(hid),
            user_id=int(maya_id) if maya_id else None,
            changed_by=getattr(owner, "id", None),
            perm=perm[:64],
            old_value=old,
            new_value=new,
            high_risk=bool(high),
            confirmed_with=confirmed_with,
            ip=(ip or None),
        )
    )


def save_state(household_id: int, maya_user, wanted: dict[str, bool], *, owner,
               confirmed_with: str | None, ip: str | None = None,
               expiry: dict | None = None) -> tuple[list[str], list[str]]:
    """Owner save. Returns (changed ids, refused ids).

    * A high-risk switch can only go from off to on when the owner
      re-confirmed (``confirmed_with`` is 'password' or 'totp').
    * ``expiry`` maps perm id -> UTC datetime or None (no expiry). High-risk
      switches that are on ALWAYS get a timer: if none is given, 24 hours.
    * Turning anything off never needs confirmation and clears the timer.
    """
    from app.builddb.table_maya_bot import MayaBotPermission

    if owner is None or bool(getattr(owner, "is_bot", False)):
        raise PermissionError("Only a signed-in owner can change Maya's permissions.")
    if is_maya(owner):
        raise PermissionError("Maya cannot change her own permissions.")
    expiry = expiry or {}
    now = datetime.utcnow()
    current = perm_state(household_id, maya_user.id)
    rows = perm_rows(household_id, maya_user.id)
    changed, refused = [], []
    for pid, perm in CATALOG_BY_ID.items():
        if pid not in wanted:
            continue
        new = bool(wanted[pid]) and perm["implemented"]
        old = bool(current.get(pid))
        row = rows.get(pid)
        if new and not old and perm["high_risk"] and not confirmed_with:
            refused.append(pid)
            continue
        want_exp = None
        if new:
            if pid in expiry:
                want_exp = expiry[pid]
            elif old and row is not None:
                want_exp = row.expires_at  # untouched timer keeps running
            if perm["high_risk"] and want_exp is None:
                unit, n = HIGH_RISK_DEFAULT_EXPIRY
                want_exp = parse_expiry(unit, n, now=now)
        old_exp = row.expires_at if (row is not None and old) else None
        if (new and old and perm["high_risk"] and not confirmed_with and want_exp is not None
                and (old_exp is None or want_exp > old_exp)):
            refused.append(pid)  # extending a high-risk timer needs the owner to re-confirm
            continue
        if new == old and row is not None and want_exp == old_exp:
            continue
        if row is None:
            row = MayaBotPermission(household_id=int(household_id), user_id=int(maya_user.id), perm=pid)
            db.session.add(row)
        row.enabled = new
        row.expires_at = want_exp if new else None
        row.updated_by = owner.id
        row.updated_at = now
        if new != old or want_exp != old_exp:
            how = confirmed_with if (new and perm["high_risk"] and not old) else None
            if new and want_exp is not None:
                how = ((how + ",") if how else "") + "timer"
            _log(household_id, maya_user.id, owner, pid, old, new, perm["high_risk"], (how or None) and how[:16], ip)
            changed.append(pid)
    if changed:
        from app.builddb.table_household_activity import HouseholdActivity

        db.session.add(
            HouseholdActivity(
                household_id=int(household_id),
                user_id=owner.id,
                action="maya.perms",
                summary=f"{(owner.name or owner.username or 'Owner').split()[0]} changed {len(changed)} Maya permission(s)",
                target_table="maya_bot_permissions",
                target_id=int(maya_user.id),
                new_json={"changed": changed[:80],
                          "timers": {p: (rows[p].expires_at.isoformat() if p in rows and rows[p].expires_at else None)
                                     for p in changed[:80] if p in rows}},
                reversible=False,
            )
        )
    db.session.commit()
    return changed, refused


def capabilities(user) -> dict:
    state = perm_state(user.household_id, user.id) if user is not None else {}
    exp = perm_expiry(user.household_id, user.id) if user is not None else {}
    out = []
    for g in groups():
        out.append(
            {
                "group": g["name"],
                "permissions": [
                    {
                        "id": p["id"],
                        "label": p["label"],
                        "detail": p["detail"],
                        "high_risk": p["high_risk"],
                        "implemented": p["implemented"],
                        "on": bool(state.get(p["id"])),
                        "expires_at": (exp[p["id"]].isoformat() + "Z") if p["id"] in exp else None,
                        "remaining": remaining_text(exp.get(p["id"])) if state.get(p["id"]) else None,
                        "timer_required": p["high_risk"],
                    }
                    for p in g["perms"]
                ],
            }
        )
    return {"groups": out, "on": sorted(k for k, v in state.items() if v), "hard_limits": HARD_LIMITS}


# ---------------------------------------------------------- owner checks


def is_owner(user) -> bool:
    """The household owner for this page: a signed-in, non-bot leader."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if bool(getattr(user, "is_bot", False)):
        return False
    return bool(getattr(user, "is_leader", False))


def confirm_owner(user, password: str = "", code: str = "") -> str | None:
    """'password' or 'totp' when the owner re-proved who they are, else None."""
    if not is_owner(user):
        return None
    if password:
        try:
            if user.check_password(password):
                return "password"
        except Exception:
            pass
    code = (code or "").strip().replace(" ", "")
    if code:
        try:
            from app.utils import twofa

            secret = (twofa.twofa_settings(user) or {}).get("secret") or ""
            if secret and twofa.totp_ok(secret, code) and not twofa.totp_replay_recent(user, code):
                twofa.mark_totp_used(user, code)
                return "totp"
        except Exception:
            pass
    return None
