from app.builddb.builddb import db, evolve_table


class MaintenanceRecord(db.Model):
    __tablename__ = "maintenance_records"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    parent_type = db.Column(db.String(20), nullable=False)
    parent_id = db.Column(db.Integer, nullable=False)
    type = db.Column(db.String(80), nullable=False)
    date = db.Column(db.Date, nullable=False)
    mileage_or_hours = db.Column(db.Numeric(12, 2), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    photos = db.Column(db.JSON, nullable=True)
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())


def create_table():
    evolve_table(
        "maintenance_records",
        [
            ("household_id", "INT NOT NULL"),
            ("parent_type", "VARCHAR(20) NOT NULL"),
            ("parent_id", "INT NOT NULL"),
            ("type", "VARCHAR(80) NOT NULL"),
            ("date", "DATE NOT NULL"),
            ("mileage_or_hours", "DECIMAL(12,2) NULL"),
            ("notes", "TEXT NULL"),
            ("photos", "JSON NULL"),
            ("created_by", "INT NULL"),
        ],
        indexes=[
            ("idx_maint_household_id", "household_id"),
            ("idx_maint_parent", "parent_type, parent_id"),
        ],
    )
