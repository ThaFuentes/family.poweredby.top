from app.builddb.builddb import db, evolve_table
from app.utils.crypto import EncryptedText


class PhotoNote(db.Model):
    __tablename__ = "photo_notes"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    item_id = db.Column(db.Integer, db.ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    part_id = db.Column(db.Integer, nullable=True)
    kind = db.Column(db.String(20), nullable=False, default="photo")
    caption = db.Column(EncryptedText, nullable=True)
    image_path = db.Column(db.String(400), nullable=False)
    warranty_until = db.Column(db.Date, nullable=True)
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())

    item = db.relationship("Item", back_populates="photos")


def create_table():
    from sqlalchemy import text

    evolve_table(
        "photo_notes",
        [
            ("household_id", "INT NOT NULL"),
            ("item_id", "INT NOT NULL"),
            ("part_id", "INT NULL"),
            ("kind", "VARCHAR(20) NOT NULL DEFAULT 'photo'"),
            ("caption", "TEXT NULL"),
            ("image_path", "VARCHAR(400) NOT NULL"),
            ("warranty_until", "DATE NULL"),
            ("created_by", "INT NULL"),
        ],
        indexes=[
            ("idx_photos_household_id", "household_id"),
            ("idx_photos_item_id", "item_id"),
            ("idx_photos_part_id", "part_id"),
        ],
    )
    try:
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE `photo_notes` MODIFY `caption` TEXT NULL"))
    except Exception:
        pass
