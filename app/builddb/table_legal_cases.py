from sqlalchemy import func

from app.builddb.builddb import db, evolve_table
from app.utils.crypto import EncryptedText

CASE_STATUSES = ("open", "closed")
CASE_STATUS_LABELS = {"open": "Open", "closed": "Closed"}


class LegalCase(db.Model):
    """A household legal case. Records (notices, tickets) can join later."""

    __tablename__ = "legal_cases"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    number = db.Column(db.Integer, nullable=False)
    title = db.Column(EncryptedText, nullable=False, default="")
    status = db.Column(db.String(20), nullable=False, default="open")
    summary = db.Column(EncryptedText, nullable=True)
    extra_data = db.Column(db.JSON, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())
    updated_at = db.Column(
        db.DateTime,
        server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )

    records = db.relationship(
        "LegalRecord",
        back_populates="case",
        order_by="LegalRecord.id.asc()",
    )
    followups = db.relationship(
        "LegalFollowup",
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="LegalFollowup.id.asc()",
    )


def case_label(case) -> str:
    if case is None:
        return ""
    try:
        n = int(case.number)
    except (TypeError, ValueError):
        return "Case"
    return f"Case #{n}"


def next_case_number(household_id: int) -> int:
    n = (
        db.session.query(func.max(LegalCase.number))
        .filter(LegalCase.household_id == household_id)
        .scalar()
    )
    try:
        return int(n or 0) + 1
    except (TypeError, ValueError):
        return 1


def create_table():
    evolve_table(
        "legal_cases",
        [
            ("household_id", "INT NOT NULL"),
            ("number", "INT NOT NULL"),
            ("title", "TEXT NOT NULL"),
            ("status", "VARCHAR(20) NOT NULL DEFAULT 'open'"),
            ("summary", "TEXT NULL"),
            ("extra_data", "JSON NULL"),
            ("created_by", "INT NULL"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
            ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        ],
        indexes=[
            ("idx_legal_cases_household_id", "household_id"),
            ("idx_legal_cases_number", "household_id, number"),
            ("idx_legal_cases_status", "status"),
        ],
    )
