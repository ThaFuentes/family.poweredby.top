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
    scope = db.Column(db.String(64), nullable=True)
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
            ("scope", "VARCHAR(64) NULL"),
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
    _widen_scope()


def _widen_scope() -> None:
    """Existing databases keep the old VARCHAR(16). Either-key denials store
    `fos_bot_,fos_vault_`, which does not fit, and the audit insert then fails.
    """
    from sqlalchemy import inspect, text

    from app.builddb.builddb import db

    try:
        cols = inspect(db.engine).get_columns("bot_api_audit")
    except Exception:
        return
    scope = next((col for col in cols if col["name"] == "scope"), None)
    if scope is None:
        return
    length = getattr(scope.get("type"), "length", None)
    if length is not None and int(length) >= 64:
        return
    with db.engine.begin() as conn:
        conn.execute(text("ALTER TABLE `bot_api_audit` MODIFY COLUMN `scope` VARCHAR(64) NULL"))