"""One row per download of a shared file — who, where, and when."""
from app.builddb.builddb import db, evolve_table


class SharedFileDownload(db.Model):
    """A download of a shared file. user_id is empty for link visitors."""

    __tablename__ = "shared_file_downloads"

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
    ip = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)
    downloaded_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())


def create_table():
    evolve_table(
        "shared_file_downloads",
        [
            ("household_id", "INT NOT NULL"),
            ("file_id", "INT NOT NULL"),
            ("user_id", "INT NULL"),
            ("ip", "VARCHAR(64) NULL"),
            ("user_agent", "VARCHAR(255) NULL"),
            ("downloaded_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ],
        indexes=[
            ("idx_shared_file_downloads_file", "file_id"),
            ("idx_shared_file_downloads_household", "household_id"),
        ],
    )
