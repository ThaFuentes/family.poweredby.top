from app.builddb.builddb import db, evolve_table
from app.utils.crypto import EncryptedText

ITEM_TYPES = ("grocery", "tool", "vehicle", "house", "custom")


class Item(db.Model):
    __tablename__ = "items"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    item_type = db.Column(db.String(20), nullable=False, default="custom")
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(100), nullable=True)
    tags = db.Column(db.JSON, nullable=True)
    barcode = db.Column(db.String(80), nullable=True)
    notes = db.Column(EncryptedText, nullable=True)
    created_by = db.Column(db.Integer, nullable=True)
    linked_item_id = db.Column(db.Integer, nullable=True)
    extra_data = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())
    updated_at = db.Column(
        db.DateTime,
        server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )

    grocery = db.relationship("GroceryItem", back_populates="item", uselist=False, cascade="all, delete-orphan")
    tool = db.relationship("Tool", back_populates="item", uselist=False, cascade="all, delete-orphan")
    vehicle = db.relationship("Vehicle", back_populates="item", uselist=False, cascade="all, delete-orphan")
    photos = db.relationship("PhotoNote", back_populates="item", cascade="all, delete-orphan")


def create_table():
    evolve_table(
        "items",
        [
            ("household_id", "INT NOT NULL"),
            ("item_type", "VARCHAR(20) NOT NULL DEFAULT 'custom'"),
            ("name", "VARCHAR(200) NOT NULL"),
            ("category", "VARCHAR(100) NULL"),
            ("tags", "JSON NULL"),
            ("barcode", "VARCHAR(80) NULL"),
            ("notes", "TEXT NULL"),
            ("created_by", "INT NULL"),
            ("linked_item_id", "INT NULL"),
            ("extra_data", "JSON NULL"),
        ],
        indexes=[
            ("idx_items_household_id", "household_id"),
            ("idx_items_barcode", "barcode"),
            ("idx_items_type", "item_type"),
            ("idx_items_household_barcode", "household_id, barcode"),
            ("idx_items_linked", "household_id, linked_item_id"),
        ],
    )
    from sqlalchemy import text

    try:
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX `idx_items_hh_barcode_uq` "
                    "ON `items` (`household_id`, `barcode`)"
                )
            )
    except Exception:
        pass
