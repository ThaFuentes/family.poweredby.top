from app.builddb.builddb import db, evolve_table


class BotApiAudit(db.Model):
    """One row per bot API event: key exchange, call, denial, revoke.

    Separate from `household_activity` because this is machine traffic and
    must survive a leader clearing the human What-happened log.
    """

    __tablename__ = "bot_api_audit"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=True
    )
    user_id = db.Column(db.Integer, nullable=True)
    key_id = db.Column(db.Integer, nullable=True)
    session_id = db.Column(db.Integer, nullable=True)
    scope = db.Column(db.String(16), nullable=True)
    event = db.Column(db.String(40), nullable=False, default="call")
    method = db.Column(db.String(10), nullable=True)
    path = db.Column(db.String(160), nullable=True)
    status = db.Column(db.Integer, nullable=True)
    outcome = db.Column(db.String(40), nullable=True)
    ip = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(200), nullable=True)
    detail_json = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())


def create_table():
    evolve_table(
        "bot_api_audit",
        [
            ("household_id", "INT NULL"),
            ("user_id", "INT NULL"),
            ("key_id", "INT NULL"),
            ("session_id", "INT NULL"),
            ("scope", "VARCHAR(16) NULL"),
            ("event", "VARCHAR(40) NOT NULL DEFAULT 'call'"),
            ("method", "VARCHAR(10) NULL"),
            ("path", "VARCHAR(160) NULL"),
            ("status", "INT NULL"),
            ("outcome", "VARCHAR(40) NULL"),
            ("ip", "VARCHAR(64) NULL"),
            ("user_agent", "VARCHAR(200) NULL"),
            ("detail_json", "JSON NULL"),
        ],
        indexes=[
            ("idx_bot_api_audit_household", "household_id, created_at"),
            ("idx_bot_api_audit_user", "user_id"),
            ("idx_bot_api_audit_event", "event"),
        ],
    )