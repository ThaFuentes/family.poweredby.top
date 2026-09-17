from app.builddb.builddb import db, evolve_table
from app.utils.crypto import EncryptedText

FOLLOWUP_KINDS = ("note", "link", "email", "file")
FOLLOWUP_LABELS = {
    "note": "Note",
    "link": "Link",
    "email": "Email",
    "file": "File",
}


class LegalFollowup(db.Model):
    """A note, link, email, or file on a case — the running file."""

    __tablename__ = "legal_followups"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    case_id = db.Column(
        db.Integer, db.ForeignKey("legal_cases.id", ondelete="CASCADE"), nullable=False
    )
    kind = db.Column(db.String(20), nullable=False, default="note")
    title = db.Column(EncryptedText, nullable=True)
    body = db.Column(EncryptedText, nullable=True)
    url = db.Column(EncryptedText, nullable=True)
    extra_data = db.Column(db.JSON, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())

    case = db.relationship("LegalCase", back_populates="followups")
    files = db.relationship(
        "LegalFile",
        back_populates="followup",
        cascade="all, delete-orphan",
        order_by="LegalFile.id.asc()",
    )


def create_table():
    evolve_table(
        "legal_followups",
        [
            ("household_id", "INT NOT NULL"),
            ("case_id", "INT NOT NULL"),
            ("kind", "VARCHAR(20) NOT NULL DEFAULT 'note'"),
            ("title", "TEXT NULL"),
            ("body", "TEXT NULL"),
            ("url", "TEXT NULL"),
            ("extra_data", "JSON NULL"),
            ("created_by", "INT NULL"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ],
        indexes=[
            ("idx_legal_followups_household_id", "household_id"),
            ("idx_legal_followups_case_id", "case_id"),
        ],
    )
