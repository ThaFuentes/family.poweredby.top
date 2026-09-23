from app.builddb.builddb import db, evolve_table
from app.utils.crypto import EncryptedText


class Tool(db.Model):
    __tablename__ = "tools"

    item_id = db.Column(
        db.Integer, db.ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    type = db.Column(db.String(80), nullable=True)
    power_source = db.Column(db.String(40), nullable=True)
    oil_type = db.Column(db.String(80), nullable=True)
    oil_needs = db.Column(db.String(200), nullable=True)
    oil_capacity = db.Column(db.String(40), nullable=True)
    last_oil_date = db.Column(db.Date, nullable=True)
    last_oil_hours = db.Column(db.Integer, nullable=True)
    oil_interval_hours = db.Column(db.Integer, nullable=True)
    oil_interval_months = db.Column(db.Integer, nullable=True)
    next_oil_due_date = db.Column(db.Date, nullable=True)
    next_oil_due_hours = db.Column(db.Integer, nullable=True)
    fuel_type = db.Column(db.String(80), nullable=True)
    usage_notes = db.Column(EncryptedText, nullable=True)
    maintenance_interval_hours = db.Column(db.Integer, nullable=True)
    last_maintenance_at = db.Column(db.DateTime, nullable=True)
    hours_used = db.Column(db.Numeric(12, 2), nullable=True)
    model = db.Column(db.String(120), nullable=True)
    serial_number = db.Column(db.String(120), nullable=True)
    asset_id = db.Column(db.String(80), nullable=True)
    extra_data = db.Column(db.JSON, nullable=True)

    item = db.relationship("Item", back_populates="tool")


def create_table():
    evolve_table(
        "tools",
        [
            ("household_id", "INT NOT NULL"),
            ("type", "VARCHAR(80) NULL"),
            ("power_source", "VARCHAR(40) NULL"),
            ("oil_type", "VARCHAR(80) NULL"),
            ("oil_needs", "VARCHAR(200) NULL"),
            ("oil_capacity", "VARCHAR(40) NULL"),
            ("last_oil_date", "DATE NULL"),
            ("last_oil_hours", "INT NULL"),
            ("oil_interval_hours", "INT NULL"),
            ("oil_interval_months", "INT NULL"),
            ("next_oil_due_date", "DATE NULL"),
            ("next_oil_due_hours", "INT NULL"),
            ("fuel_type", "VARCHAR(80) NULL"),
            ("usage_notes", "TEXT NULL"),
            ("maintenance_interval_hours", "INT NULL"),
            ("last_maintenance_at", "TIMESTAMP NULL"),
            ("hours_used", "DECIMAL(12,2) NULL"),
            ("model", "VARCHAR(120) NULL"),
            ("serial_number", "VARCHAR(120) NULL"),
            ("asset_id", "VARCHAR(80) NULL"),
            ("extra_data", "JSON NULL"),
        ],
        indexes=[("idx_tools_household_id", "household_id")],
    )
