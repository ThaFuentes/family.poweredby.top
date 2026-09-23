"""A short Ask transcript per person. The cookie only holds a snippet of this."""
from app.builddb.builddb import db, evolve_table
from app.utils.crypto import EncryptedText


class AskTurn(db.Model):
    __tablename__ = "ask_turns"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="user")
    room = db.Column(db.String(20), nullable=False, default="house")
    body = db.Column(EncryptedText, nullable=False, default="")
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())


def create_table():
    evolve_table(
        "ask_turns",
        [
            ("household_id", "INT NOT NULL"),
            ("user_id", "INT NOT NULL"),
            ("role", "VARCHAR(20) NOT NULL DEFAULT 'user'"),
            ("room", "VARCHAR(20) NOT NULL DEFAULT 'house'"),
            ("body", "TEXT NOT NULL"),
        ],
        indexes=[
            ("idx_ask_turns_household_id", "household_id"),
            ("idx_ask_turns_user_id", "user_id"),
            ("idx_ask_turns_room", "household_id, user_id, room"),
        ],
    )
