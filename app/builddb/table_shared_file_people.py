"""Named household people who may open one shared file."""
from app.builddb.builddb import db, evolve_table


class SharedFilePerson(db.Model):
    __tablename__ = "shared_file_people"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    file_id = db.Column(
        db.Integer, db.ForeignKey("shared_files.id", ondelete="CASCADE"), nullable=False
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())

    file = db.relationship("SharedFile", back_populates="people")


def create_table():
    evolve_table(
        "shared_file_people",
        [
            ("household_id", "INT NOT NULL"),
            ("file_id", "INT NOT NULL"),
            ("user_id", "INT NOT NULL"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ],
        indexes=[
            ("idx_shared_file_people_file", "file_id"),
            ("idx_shared_file_people_user", "user_id"),
            ("uq_shared_file_people_pair", "file_id, user_id", True),
        ],
    )
