from app.builddb.builddb import db, evolve_table

SHARE_MODES = ("household", "personal", "selected")


class VaultEntry(db.Model):
    """Household password vault row. Secret columns are ciphertext, never plaintext."""

    __tablename__ = "vault_entries"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    created_by = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    share_mode = db.Column(db.String(20), nullable=False, default="personal")
    title = db.Column(db.Text, nullable=False, default="")
    login = db.Column(db.Text, nullable=True)
    secret = db.Column(db.Text, nullable=True)
    url = db.Column(db.Text, nullable=True)
    purpose = db.Column(db.Text, nullable=True)
    details = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())
    updated_at = db.Column(
        db.DateTime,
        server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )

    grants = db.relationship(
        "VaultGrant",
        back_populates="entry",
        cascade="all, delete-orphan",
        order_by="VaultGrant.id.asc()",
    )


def create_table():
    evolve_table(
        "vault_entries",
        [
            ("household_id", "INT NOT NULL"),
            ("created_by", "INT NULL"),
            ("share_mode", "VARCHAR(20) NOT NULL DEFAULT 'personal'"),
            ("title", "TEXT NOT NULL"),
            ("login", "TEXT NULL"),
            ("secret", "TEXT NULL"),
            ("url", "TEXT NULL"),
            ("purpose", "TEXT NULL"),
            ("details", "TEXT NULL"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
            ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        ],
        indexes=[
            ("idx_vault_entries_household_id", "household_id"),
            ("idx_vault_entries_created_by", "created_by"),
            ("idx_vault_entries_share_mode", "share_mode"),
        ],
    )
