"""Maya's bot API: who Maya is, her permission checklist, the owner's change
log, the household recycle bin, and archived file versions.

Five small tables, all household-scoped:

* ``maya_bot_accounts``     one row per household: which bot user is Maya.
* ``maya_bot_permissions``  one row per (household, user, permission) the owner
                            has saved. A missing row means the catalog default.
* ``maya_bot_perm_log``     every owner change to the checklist (audit).
* ``household_trash``       raw-row snapshots of removed things so a removal
                            (by Maya or by a person in the UI) can be put back.
* ``household_file_versions`` old file bytes (still encrypted) moved outside
                            the docroot when a file is replaced or removed.
"""
import os

from sqlalchemy import text

from app.builddb.builddb import db, evolve_table


class MayaBotAccount(db.Model):
    __tablename__ = "maya_bot_accounts"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    set_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())
    updated_at = db.Column(
        db.DateTime,
        server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )


class MayaBotPermission(db.Model):
    __tablename__ = "maya_bot_permissions"
    __table_args__ = (
        db.UniqueConstraint("household_id", "user_id", "perm", name="uq_maya_perm"),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    perm = db.Column(db.String(64), nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    expires_at = db.Column(db.DateTime, nullable=True)  # auto-off time (UTC); NULL = no expiry
    updated_by = db.Column(db.Integer, nullable=True)
    updated_at = db.Column(
        db.DateTime,
        server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )


class MayaBotPermLog(db.Model):
    __tablename__ = "maya_bot_perm_log"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    user_id = db.Column(db.Integer, nullable=True)  # Maya's account
    changed_by = db.Column(db.Integer, nullable=True)  # the owner
    perm = db.Column(db.String(64), nullable=False)
    old_value = db.Column(db.Boolean, nullable=True)
    new_value = db.Column(db.Boolean, nullable=True)
    high_risk = db.Column(db.Boolean, nullable=False, default=False)
    confirmed_with = db.Column(db.String(16), nullable=True)  # password | totp
    ip = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())


class HouseholdTrash(db.Model):
    __tablename__ = "household_trash"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    target_table = db.Column(db.String(40), nullable=False)
    target_id = db.Column(db.Integer, nullable=False)
    label = db.Column(db.String(240), nullable=True)
    rows_json = db.Column(db.JSON, nullable=True)  # [{"table":..,"row":{raw columns}}]
    files_json = db.Column(db.JSON, nullable=True)  # [{"rel":..,"archived":..}]
    deleted_by = db.Column(db.Integer, nullable=True)
    via = db.Column(db.String(16), nullable=True)  # ui | maya
    deleted_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())
    restored_at = db.Column(db.DateTime, nullable=True)
    restored_by = db.Column(db.Integer, nullable=True)
    purged_at = db.Column(db.DateTime, nullable=True)
    purged_by = db.Column(db.Integer, nullable=True)


class HouseholdFileVersion(db.Model):
    __tablename__ = "household_file_versions"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    kind = db.Column(db.String(20), nullable=False)  # note_file | photo | legal_file
    row_id = db.Column(db.Integer, nullable=False)
    stored_rel = db.Column(db.String(400), nullable=False)  # where it lived under uploads/
    archived_path = db.Column(db.String(500), nullable=False)  # outside the docroot
    original_name = db.Column(db.String(200), nullable=True)
    mime = db.Column(db.String(80), nullable=True)
    reason = db.Column(db.String(16), nullable=True)  # replace | remove
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())
    restored_at = db.Column(db.DateTime, nullable=True)


def _seed_maya_account():
    """Default Maya to the configured bot (household 'fuentes', user 'grokbots').

    Only inserts when that household has no Maya row yet and the user exists
    and is a bot. Never changes an owner's later choice.
    """
    handle = (os.getenv("MAYA_BOT_HOUSEHOLD") or "fuentes").strip().lower()
    username = (os.getenv("MAYA_BOT_USERNAME") or "grokbots").strip().lower()
    try:
        with db.engine.begin() as conn:
            row = conn.execute(
                text(
                    "SELECT u.id AS uid, u.household_id AS hid FROM users u "
                    "JOIN households h ON h.id = u.household_id "
                    "WHERE LOWER(h.handle) = :h AND LOWER(u.username) = :u AND u.is_bot = 1"
                ),
                {"h": handle, "u": username},
            ).fetchone()
            if row is None:
                return
            have = conn.execute(
                text("SELECT id FROM maya_bot_accounts WHERE household_id = :hid"),
                {"hid": row.hid},
            ).fetchone()
            if have is None:
                conn.execute(
                    text(
                        "INSERT INTO maya_bot_accounts (household_id, user_id, enabled) "
                        "VALUES (:hid, :uid, 1)"
                    ),
                    {"hid": row.hid, "uid": row.uid},
                )
    except Exception as exc:
        print(f"[BUILD-DB] maya seed skipped: {exc}", flush=True)


def create_table():
    evolve_table(
        "maya_bot_accounts",
        [("enabled", "TINYINT(1) NOT NULL DEFAULT 1"), ("set_by", "INT NULL")],
    )
    evolve_table(
        "maya_bot_permissions",
        [("updated_by", "INT NULL"), ("expires_at", "DATETIME NULL")],
        indexes=[("idx_maya_perm_user", "household_id, user_id"), ("idx_maya_perm_expiry", "enabled, expires_at")],
    )
    evolve_table(
        "maya_bot_perm_log",
        [("confirmed_with", "VARCHAR(16) NULL"), ("ip", "VARCHAR(64) NULL")],
        indexes=[("idx_maya_perm_log_house", "household_id, created_at")],
    )
    evolve_table(
        "household_trash",
        [("purged_at", "DATETIME NULL"), ("purged_by", "INT NULL"), ("via", "VARCHAR(16) NULL")],
        indexes=[("idx_household_trash_house", "household_id, deleted_at")],
    )
    evolve_table(
        "household_file_versions",
        [("reason", "VARCHAR(16) NULL"), ("restored_at", "DATETIME NULL")],
        indexes=[("idx_file_versions_row", "household_id, kind, row_id")],
    )
    _seed_maya_account()
