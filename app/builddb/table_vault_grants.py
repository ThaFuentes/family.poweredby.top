from app.builddb.builddb import db, evolve_table


class VaultGrant(db.Model):
    """Who else may open a vault entry, until when, and whether they opened it."""

    __tablename__ = "vault_grants"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    entry_id = db.Column(
        db.Integer, db.ForeignKey("vault_entries.id", ondelete="CASCADE"), nullable=False
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    granted_by = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    duration_key = db.Column(db.String(20), nullable=False, default="forever")
    expires_at = db.Column(db.DateTime, nullable=True)
    last_seen_at = db.Column(db.DateTime, nullable=True)
    seen_count = db.Column(db.Integer, nullable=False, default=0)
    revoked_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())

    entry = db.relationship("VaultEntry", back_populates="grants")


def create_table():
    evolve_table(
        "vault_grants",
        [
            ("household_id", "INT NOT NULL"),
            ("entry_id", "INT NOT NULL"),
            ("user_id", "INT NOT NULL"),
            ("granted_by", "INT NULL"),
            ("duration_key", "VARCHAR(20) NOT NULL DEFAULT 'forever'"),
            ("expires_at", "DATETIME NULL DEFAULT NULL"),
            ("last_seen_at", "DATETIME NULL DEFAULT NULL"),
            ("seen_count", "INT NOT NULL DEFAULT 0"),
            ("revoked_at", "DATETIME NULL DEFAULT NULL"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ],
        indexes=[
            ("idx_vault_grants_household_id", "household_id"),
            ("idx_vault_grants_entry_id", "entry_id"),
            ("idx_vault_grants_user_id", "user_id"),
            ("idx_vault_grants_entry_user", "entry_id, user_id"),
        ],
    )
    _drop_timestamp_touch("vault_grants", ("expires_at", "last_seen_at", "revoked_at"))


def _drop_timestamp_touch(table: str, cols: tuple[str, ...]) -> None:
    """MariaDB first TIMESTAMP can ON UPDATE CURRENT_TIMESTAMP and kill forever grants."""
    from sqlalchemy import text

    for col in cols:
        try:
            db.session.execute(
                text(f"ALTER TABLE `{table}` MODIFY `{col}` DATETIME NULL DEFAULT NULL")
            )
            db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
