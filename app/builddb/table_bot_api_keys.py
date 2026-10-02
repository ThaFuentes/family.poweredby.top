from app.builddb.builddb import db, evolve_table

# One bot account can hold both scopes; the prefix carries the scope.
SCOPES = ("fos_bot_", "fos_vault_")
KEY_ROLES = ("primary", "twofa")
HASH_LEN = 64


class BotApiKey(db.Model):
    """One issued bot API key. Only the hash is ever stored.

    A scope is carried by the key prefix itself, so a `fos_vault_` key can
    never satisfy a `fos_bot_` route check. Keys come in pairs (primary +
    twofa) that share `pair_id`; revoking one revokes the pair.
    """

    __tablename__ = "bot_api_keys"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    scope = db.Column(db.String(16), nullable=False, default="fos_bot_")
    key_role = db.Column(db.String(10), nullable=False, default="primary")
    key_hash = db.Column(db.String(HASH_LEN), nullable=False)
    key_tail = db.Column(db.String(12), nullable=True)
    pair_id = db.Column(db.String(32), nullable=False)
    label = db.Column(db.String(120), nullable=True)
    created_by = db.Column(db.Integer, nullable=True)
    issued_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    revoked_at = db.Column(db.DateTime, nullable=True)
    revoked_by = db.Column(db.Integer, nullable=True)
    last_used_at = db.Column(db.DateTime, nullable=True)
    use_count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None


def create_table():
    evolve_table(
        "bot_api_keys",
        [
            ("household_id", "INT NOT NULL"),
            ("user_id", "INT NOT NULL"),
            ("scope", "VARCHAR(16) NOT NULL DEFAULT 'fos_bot_'"),
            ("key_role", "VARCHAR(10) NOT NULL DEFAULT 'primary'"),
            ("key_hash", f"VARCHAR({HASH_LEN}) NOT NULL"),
            ("key_tail", "VARCHAR(12) NULL"),
            ("pair_id", "VARCHAR(32) NOT NULL"),
            ("label", "VARCHAR(120) NULL"),
            ("created_by", "INT NULL"),
            ("issued_at", "TIMESTAMP NULL DEFAULT NULL"),
            ("expires_at", "TIMESTAMP NULL DEFAULT NULL"),
            ("revoked_at", "TIMESTAMP NULL DEFAULT NULL"),
            ("revoked_by", "INT NULL"),
            ("last_used_at", "TIMESTAMP NULL DEFAULT NULL"),
            ("use_count", "INT NOT NULL DEFAULT 0"),
        ],
        indexes=[
            ("idx_bot_api_keys_hash", "key_hash"),
            ("idx_bot_api_keys_user", "household_id, user_id"),
            ("idx_bot_api_keys_pair", "pair_id"),
            ("idx_bot_api_keys_scope", "scope"),
        ],
    )