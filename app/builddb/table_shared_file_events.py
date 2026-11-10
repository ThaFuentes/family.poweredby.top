"""Emails sent and link changes for one shared file. Downloads have their own table."""
from app.builddb.builddb import db, evolve_table


class SharedFileEvent(db.Model):
    __tablename__ = "shared_file_events"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    file_id = db.Column(
        db.Integer, db.ForeignKey("shared_files.id", ondelete="CASCADE"), nullable=False
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # email | access | revoke | create
    kind = db.Column(db.String(20), nullable=False)
    detail = db.Column(db.Text, nullable=True)
    ok = db.Column(db.Boolean, nullable=False, default=True)
    ip = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())


def create_table():
    evolve_table(
        "shared_file_events",
        [
            ("household_id", "INT NOT NULL"),
            ("file_id", "INT NOT NULL"),
            ("user_id", "INT NULL"),
            ("kind", "VARCHAR(20) NOT NULL"),
            ("detail", "TEXT NULL"),
            ("ok", "TINYINT(1) NOT NULL DEFAULT 1"),
            ("ip", "VARCHAR(64) NULL"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ],
        indexes=[
            ("idx_shared_file_events_file", "file_id"),
            ("idx_shared_file_events_household", "household_id"),
        ],
    )
