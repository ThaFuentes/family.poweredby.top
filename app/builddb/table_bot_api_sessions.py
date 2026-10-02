from app.builddb.builddb import db, evolve_table

HASH_LEN = 64


class BotApiSession(db.Model):
    """A short-lived Bearer token produced by exchanging a key pair once.

    The emailed twofa key is spent at exchange time and never travels again.
    Store the hash only: a database copy cannot be replayed as a token.
    """

    __tablename__ = "bot_api_sessions"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    key_id = db.Column(
        db.Integer, db.ForeignKey("bot_api_keys.id", ondelete="CASCADE"), nullable=True
    )
    scope = db.Column(db.String(16), nullable=False, default="fos_bot_")
    pair_id = db.Column(db.String(32), nullable=True)
    token_hash = db.Column(db.String(HASH_LEN), nullable=False)
    token_tail = db.Column(db.String(10), nullable=True)
    issued_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    revoked_at = db.Column(db.DateTime, nullable=True)
    last_used_at = db.Column(db.DateTime, nullable=True)
    request_count = db.Column(db.Integer, nullable=False, default=0)
    created_ip = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())


def create_table():
    evolve_table(
        "bot_api_sessions",
        [
            ("household_id", "INT NOT NULL"),
            ("user_id", "INT NOT NULL"),
            ("key_id", "INT NULL"),
            ("scope", "VARCHAR(16) NOT NULL DEFAULT 'fos_bot_'"),
            ("pair_id", "VARCHAR(32) NULL"),
            ("token_hash", f"VARCHAR({HASH_LEN}) NOT NULL"),
            ("token_tail", "VARCHAR(10) NULL"),
            ("issued_at", "TIMESTAMP NULL DEFAULT NULL"),
            ("expires_at", "TIMESTAMP NULL DEFAULT NULL"),
            ("revoked_at", "TIMESTAMP NULL DEFAULT NULL"),
            ("last_used_at", "TIMESTAMP NULL DEFAULT NULL"),
            ("request_count", "INT NOT NULL DEFAULT 0"),
            ("created_ip", "VARCHAR(64) NULL"),
        ],
        indexes=[
            ("idx_bot_api_sessions_hash", "token_hash"),
            ("idx_bot_api_sessions_user", "household_id, user_id"),
            ("idx_bot_api_sessions_pair", "pair_id"),
        ],
    )