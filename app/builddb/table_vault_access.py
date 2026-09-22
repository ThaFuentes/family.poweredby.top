from app.builddb.builddb import db, evolve_table


class VaultAccess(db.Model):
    """Each time someone opens or copies a vault entry."""

    __tablename__ = "vault_access"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    entry_id = db.Column(
        db.Integer, db.ForeignKey("vault_entries.id", ondelete="CASCADE"), nullable=False
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action = db.Column(db.String(40), nullable=False, default="view")
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())

    entry = db.relationship("VaultEntry", back_populates="access")


def create_table():
    evolve_table(
        "vault_access",
        [
            ("household_id", "INT NOT NULL"),
            ("entry_id", "INT NOT NULL"),
            ("user_id", "INT NULL"),
            ("action", "VARCHAR(40) NOT NULL DEFAULT 'view'"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ],
        indexes=[
            ("idx_vault_access_household_id", "household_id"),
            ("idx_vault_access_entry_id", "entry_id"),
            ("idx_vault_access_user_id", "user_id"),
            ("idx_vault_access_entry_created", "entry_id, created_at"),
        ],
    )
