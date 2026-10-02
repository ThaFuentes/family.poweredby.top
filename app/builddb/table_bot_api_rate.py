from app.builddb.builddb import db, evolve_table


class BotApiRate(db.Model):
    """Fixed-window request counter, shared across every Passenger worker.

    The wrapper's in-memory throttle is per-process and IP-shaped. A bot key
    needs a limit that survives a worker recycle, so this lives in the
    database and is keyed by subject ("k:12" for a key, "ip:1.2.3.4").
    """

    __tablename__ = "bot_api_rate"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    subject = db.Column(db.String(80), nullable=False)
    window_start = db.Column(db.DateTime, nullable=False)
    count = db.Column(db.Integer, nullable=False, default=0)
    updated_at = db.Column(
        db.DateTime,
        server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )


def create_table():
    evolve_table(
        "bot_api_rate",
        [
            ("subject", "VARCHAR(80) NOT NULL"),
            ("window_start", "TIMESTAMP NULL DEFAULT NULL"),
            ("count", "INT NOT NULL DEFAULT 0"),
        ],
        indexes=[
            ("idx_bot_api_rate_subject", "subject, window_start"),
        ],
    )