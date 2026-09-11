from app.builddb.builddb import db, evolve_table
from app.utils.crypto import EncryptedText


class VehiclePart(db.Model):
    """Installed / spare / retired part on a household vehicle."""

    __tablename__ = "vehicle_parts"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    vehicle_item_id = db.Column(
        db.Integer, db.ForeignKey("items.id", ondelete="CASCADE"), nullable=False
    )
    catalog_item_id = db.Column(db.Integer, nullable=True)
    system = db.Column(db.String(40), nullable=False, default="other")
    slot = db.Column(db.String(40), nullable=False, default="misc")
    name = db.Column(db.String(200), nullable=False)
    brand = db.Column(db.String(120), nullable=True)
    spec = db.Column(db.String(160), nullable=True)
    part_number = db.Column(db.String(80), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="installed")
    is_current = db.Column(db.Boolean, nullable=False, default=True)
    installed_on = db.Column(db.Date, nullable=True)
    installed_mileage = db.Column(db.Integer, nullable=True)
    notes = db.Column(EncryptedText, nullable=True)
    source = db.Column(db.String(200), nullable=True)
    cost = db.Column(db.Numeric(12, 2), nullable=True)
    warranty_until = db.Column(db.Date, nullable=True)
    replaced_id = db.Column(db.Integer, nullable=True)
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())
    updated_at = db.Column(
        db.DateTime,
        server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )


def create_table():
    evolve_table(
        "vehicle_parts",
        [
            ("household_id", "INT NOT NULL"),
            ("vehicle_item_id", "INT NOT NULL"),
            ("catalog_item_id", "INT NULL"),
            ("system", "VARCHAR(40) NOT NULL DEFAULT 'other'"),
            ("slot", "VARCHAR(40) NOT NULL DEFAULT 'misc'"),
            ("name", "VARCHAR(200) NOT NULL"),
            ("brand", "VARCHAR(120) NULL"),
            ("spec", "VARCHAR(160) NULL"),
            ("part_number", "VARCHAR(80) NULL"),
            ("status", "VARCHAR(20) NOT NULL DEFAULT 'installed'"),
            ("is_current", "TINYINT(1) NOT NULL DEFAULT 1"),
            ("installed_on", "DATE NULL"),
            ("installed_mileage", "INT NULL"),
            ("notes", "TEXT NULL"),
            ("source", "VARCHAR(200) NULL"),
            ("cost", "DECIMAL(12,2) NULL"),
            ("warranty_until", "DATE NULL"),
            ("replaced_id", "INT NULL"),
            ("created_by", "INT NULL"),
        ],
        indexes=[
            ("idx_vparts_household", "household_id"),
            ("idx_vparts_vehicle", "vehicle_item_id"),
            ("idx_vparts_slot", "vehicle_item_id, system, slot, is_current"),
            ("idx_vparts_catalog", "catalog_item_id"),
        ],
    )
