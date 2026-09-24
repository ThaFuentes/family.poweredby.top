from app.builddb.builddb import db, evolve_table
from app.utils.crypto import EncryptedText

LOG_KINDS = ("miles", "hours", "fillup", "repair", "note", "code", "trip")
LOG_LABELS = {
    "miles": "Miles",
    "hours": "Hours",
    "fillup": "Fill-up",
    "repair": "Repair",
    "note": "Note",
    "code": "Error code",
    "trip": "Trip",
}


class ItemLog(db.Model):
    """Miles, hours, fill-ups, repairs, notes on a vehicle / tool / house."""

    __tablename__ = "item_logs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    item_id = db.Column(
        db.Integer, db.ForeignKey("items.id", ondelete="CASCADE"), nullable=False
    )
    kind = db.Column(db.String(20), nullable=False, default="note")
    happened_on = db.Column(db.Date, nullable=True)
    reading = db.Column(db.Numeric(12, 2), nullable=True)
    gallons = db.Column(db.Numeric(12, 3), nullable=True)
    cost = db.Column(db.Numeric(12, 2), nullable=True)
    title = db.Column(db.String(200), nullable=True)
    notes = db.Column(EncryptedText, nullable=True)
    extra_data = db.Column(db.JSON, nullable=True)
    maintenance_id = db.Column(db.Integer, nullable=True)
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())

    item = db.relationship("Item")


def create_table():
    evolve_table(
        "item_logs",
        [
            ("household_id", "INT NOT NULL"),
            ("item_id", "INT NOT NULL"),
            ("kind", "VARCHAR(20) NOT NULL DEFAULT 'note'"),
            ("happened_on", "DATE NULL"),
            ("reading", "DECIMAL(12,2) NULL"),
            ("gallons", "DECIMAL(12,3) NULL"),
            ("cost", "DECIMAL(12,2) NULL"),
            ("title", "VARCHAR(200) NULL"),
            ("notes", "TEXT NULL"),
            ("extra_data", "JSON NULL"),
            ("maintenance_id", "INT NULL"),
            ("created_by", "INT NULL"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ],
        indexes=[
            ("idx_item_logs_household_id", "household_id"),
            ("idx_item_logs_item_id", "item_id"),
            ("idx_item_logs_kind", "kind"),
        ],
    )
