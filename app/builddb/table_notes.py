from app.builddb.builddb import db, evolve_table
from app.utils.crypto import EncryptedText

VISIBILITY = ("personal", "household")


class Note(db.Model):
    __tablename__ = "notes"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id", ondelete="SET NULL"), nullable=True)
    visibility = db.Column(db.String(20), nullable=False, default="personal")
    title = db.Column(EncryptedText, nullable=False, default="")
    body = db.Column(EncryptedText, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())
    updated_at = db.Column(
        db.DateTime,
        server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )

    item = db.relationship("Item")


def create_table():
    evolve_table(
        "notes",
        [
            ("household_id", "INT NOT NULL"),
            ("user_id", "INT NOT NULL"),
            ("item_id", "INT NULL"),
            ("visibility", "VARCHAR(20) NOT NULL DEFAULT 'personal'"),
            ("title", "TEXT NOT NULL"),
            ("body", "TEXT NULL"),
        ],
        indexes=[
            ("idx_notes_household_id", "household_id"),
            ("idx_notes_user_id", "user_id"),
            ("idx_notes_item_id", "item_id"),
            ("idx_notes_visibility", "visibility"),
        ],
    )
