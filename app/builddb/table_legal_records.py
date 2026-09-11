from app.builddb.builddb import db, evolve_table
from app.utils.crypto import EncryptedText

KINDS = ("citation", "notice", "warning", "ticket", "court", "letter", "other")
STATUSES = ("open", "paid", "contested", "appealed", "dismissed", "closed")

KIND_LABELS = {
    "citation": "Citation",
    "notice": "Notice",
    "warning": "Warning",
    "ticket": "Ticket",
    "court": "Court",
    "letter": "Letter",
    "other": "Other",
}

STATUS_LABELS = {
    "open": "Open",
    "paid": "Paid",
    "contested": "Contested",
    "appealed": "Appealed",
    "dismissed": "Dismissed",
    "closed": "Closed",
}


class LegalRecord(db.Model):
    """Household paper trail: citations, notices, tickets. Encrypted at rest."""

    __tablename__ = "legal_records"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    created_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    kind = db.Column(db.String(20), nullable=False, default="citation")
    status = db.Column(db.String(20), nullable=False, default="open")
    title = db.Column(EncryptedText, nullable=False, default="")
    agency = db.Column(EncryptedText, nullable=True)
    case_number = db.Column(EncryptedText, nullable=True)
    location = db.Column(EncryptedText, nullable=True)
    issued_on = db.Column(db.Date, nullable=True)
    due_on = db.Column(db.Date, nullable=True)
    amount = db.Column(db.Numeric(12, 2), nullable=True)
    body = db.Column(EncryptedText, nullable=True)
    outcome = db.Column(EncryptedText, nullable=True)
    extra_data = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())
    updated_at = db.Column(
        db.DateTime,
        server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )

    files = db.relationship(
        "LegalFile",
        back_populates="record",
        cascade="all, delete-orphan",
        order_by="LegalFile.id.asc()",
    )


def create_table():
    evolve_table(
        "legal_records",
        [
            ("household_id", "INT NOT NULL"),
            ("created_by", "INT NULL"),
            ("kind", "VARCHAR(20) NOT NULL DEFAULT 'citation'"),
            ("status", "VARCHAR(20) NOT NULL DEFAULT 'open'"),
            ("title", "TEXT NOT NULL"),
            ("agency", "TEXT NULL"),
            ("case_number", "TEXT NULL"),
            ("location", "TEXT NULL"),
            ("issued_on", "DATE NULL"),
            ("due_on", "DATE NULL"),
            ("amount", "DECIMAL(12,2) NULL"),
            ("body", "TEXT NULL"),
            ("outcome", "TEXT NULL"),
            ("extra_data", "JSON NULL"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
            ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        ],
        indexes=[
            ("idx_legal_household_id", "household_id"),
            ("idx_legal_kind", "kind"),
            ("idx_legal_status", "status"),
            ("idx_legal_issued_on", "issued_on"),
        ],
    )
