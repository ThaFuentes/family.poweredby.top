from app.builddb.builddb import db, evolve_table
import secrets


class Household(db.Model):
    __tablename__ = "households"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(150), nullable=False)
    handle = db.Column(db.String(32), unique=True, nullable=True)
    invite_code = db.Column(db.String(32), unique=True, nullable=True)
    settings_json = db.Column(db.JSON, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    extra_data = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.current_timestamp())
    updated_at = db.Column(
        db.DateTime,
        server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )

    users = db.relationship("User", back_populates="household")

    def rotate_invite_code(self):
        self.invite_code = secrets.token_urlsafe(8).replace("-", "").replace("_", "")[:12].upper()
        return self.invite_code


def create_table():
    evolve_table(
        "households",
        [
            ("handle", "VARCHAR(32) NULL"),
            ("invite_code", "VARCHAR(32) NULL"),
            ("settings_json", "JSON NULL"),
            ("is_active", "TINYINT(1) NOT NULL DEFAULT 1"),
            ("extra_data", "JSON NULL"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
            ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        ],
        indexes=[
            ("idx_households_invite", "invite_code"),
        ],
    )
    _backfill_handles()
    _unique_handle_index()


def _backfill_handles():
    try:
        from app.utils.identity import unique_handle

        rows = Household.query.filter(
            (Household.handle.is_(None)) | (Household.handle == "")
        ).all()
        for h in rows:
            h.handle = unique_handle(h.name or "house", exclude_id=h.id)
        if rows:
            db.session.commit()
    except Exception as exc:
        from app.builddb.builddb import _say, _rollback

        _rollback()
        _say(f"[BUILD-DB] household handle backfill: {exc}")


def _unique_handle_index():
    from sqlalchemy import text
    from app.builddb.builddb import _say, _rollback

    _rollback()
    try:
        from sqlalchemy import inspect as sa_inspect

        inspector = sa_inspect(db.engine)
        if "households" not in inspector.get_table_names():
            return
        for idx in inspector.get_indexes("households"):
            cols = idx.get("column_names") or []
            if idx.get("unique") and cols == ["handle"]:
                return
        with db.engine.begin() as conn:
            conn.execute(text("CREATE UNIQUE INDEX idx_households_handle ON households (handle)"))
            _say("[BUILD-DB] unique household handles")
    except Exception as idx_e:
        _rollback()
        _say(f"[BUILD-DB] household handle unique: {idx_e}")
