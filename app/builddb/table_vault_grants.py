from app.builddb.builddb import db, evolve_table


class VaultGrant(db.Model):
    """Who else may open a vault entry, and until when."""

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
    expires_at = db.Column(db.DateTime, nullable=True)
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
            ("expires_at", "TIMESTAMP NULL DEFAULT NULL"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ],
        indexes=[
            ("idx_vault_grants_household_id", "household_id"),
            ("idx_vault_grants_entry_id", "entry_id"),
            ("idx_vault_grants_user_id", "user_id"),
            ("idx_vault_grants_entry_user", "entry_id, user_id"),
        ],
    )
