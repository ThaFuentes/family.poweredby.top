from app.builddb.builddb import db, evolve_table
from app.utils.crypto import EncryptedText


class LegalFile(db.Model):
    """Encrypted scan / photo / PDF attached to a legal record."""

    __tablename__ = "legal_files"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    record_id = db.Column(
        db.Integer, db.ForeignKey("legal_records.id", ondelete="CASCADE"), nullable=True
    )
    case_id = db.Column(
        db.Integer, db.ForeignKey("legal_cases.id", ondelete="CASCADE"), nullable=True
    )
    followup_id = db.Column(
        db.Integer, db.ForeignKey("legal_followups.id", ondelete="CASCADE"), nullable=True
    )
    original_name = db.Column(db.String(200), nullable=True)
    stored_path = db.Column(db.String(400), nullable=False)
    mime = db.Column(db.String(80), nullable=True)
    caption = db.Column(EncryptedText, nullable=True)
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())

    record = db.relationship("LegalRecord", back_populates="files")
    followup = db.relationship("LegalFollowup", back_populates="files")


def create_table():
    evolve_table(
        "legal_files",
        [
            ("household_id", "INT NOT NULL"),
            ("record_id", "INT NULL"),
            ("case_id", "INT NULL"),
            ("followup_id", "INT NULL"),
            ("original_name", "VARCHAR(200) NULL"),
            ("stored_path", "VARCHAR(400) NOT NULL"),
            ("mime", "VARCHAR(80) NULL"),
            ("caption", "TEXT NULL"),
            ("created_by", "INT NULL"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ],
        indexes=[
            ("idx_legal_files_household_id", "household_id"),
            ("idx_legal_files_record_id", "record_id"),
            ("idx_legal_files_case_id", "case_id"),
            ("idx_legal_files_followup_id", "followup_id"),
        ],
    )
    try:
        from sqlalchemy import text

        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE `legal_files` MODIFY `record_id` INT NULL"))
    except Exception:
        pass
