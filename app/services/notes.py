"""Notes and note attachments (Notes page, item Notes tab, Maya API)."""
from __future__ import annotations

from datetime import datetime

from app.builddb.builddb import db

KEEP = object()


def resolve_item_id(raw):
    from app.builddb.table_items import Item
    from app.utils.household import scoped

    text = str(raw if raw is not None else "").strip()
    if not text.isdigit():
        return None
    item = scoped(Item).filter_by(id=int(text)).first()
    return item.id if item else None


def normalize_visibility(raw, fallback="personal"):
    from app.builddb.table_notes import VISIBILITY

    vis = (str(raw or fallback)).strip().lower()
    return vis if vis in VISIBILITY else fallback


def can_edit(note, user) -> bool:
    """Notes page rule: the author or an admin."""
    if note is None or user is None:
        return False
    if int(note.user_id or 0) == int(user.id):
        return True
    return bool(getattr(user, "is_admin", False))


def can_see(note, user) -> bool:
    if note is None or user is None:
        return False
    if int(note.user_id or 0) == int(user.id):
        return True
    return (note.visibility or "") == "household"


def create_note(*, hid: int, user_id: int, title, body=None, visibility="personal", item_id=None):
    from app.builddb.table_notes import Note

    title = (title or "").strip()
    if not title:
        return None, "Give the note a name."
    note = Note(
        household_id=hid,
        user_id=user_id,
        item_id=item_id,
        visibility=normalize_visibility(visibility),
        title=title[:500],
        body=(str(body).strip() or None) if body else None,
    )
    db.session.add(note)
    db.session.flush()
    return note, None


def update_note(note, *, title=KEEP, body=KEEP, visibility=KEEP, item_id=KEEP):
    """None on success, else the message the page shows."""
    if title is not KEEP:
        title = (title or "").strip()
        if not title:
            return "Give the note a name."
        note.title = title[:500]
    if body is not KEEP:
        note.body = (body or "").strip() or None
    if visibility is not KEEP:
        note.visibility = normalize_visibility(visibility, note.visibility)
    if item_id is not KEEP:
        note.item_id = item_id
    note.updated_at = datetime.utcnow()
    return None


def remove_note(note, *, actor_id, via="ui"):
    """Recycle bin: the note, its file rows, and the encrypted files."""
    from app.builddb.table_note_files import NoteFile
    from app.builddb.table_notes import Note
    from app.utils import maya_store

    files = list(note.files or [])
    rows = [(Note, note)] + [(NoteFile, f) for f in files]
    return maya_store.trash(
        hid=note.household_id,
        label=f"Note: {note.title or note.id}",
        rows=rows,
        files=[f.stored_path for f in files if f.stored_path],
        actor_id=actor_id,
        via=via,
    )


def remove_note_file(row, *, actor_id, via="ui"):
    from app.builddb.table_note_files import NoteFile
    from app.utils import maya_store

    return maya_store.trash(
        hid=row.household_id,
        label=f"File: {row.original_name or row.id}",
        rows=[(NoteFile, row)],
        files=[row.stored_path] if row.stored_path else [],
        actor_id=actor_id,
        via=via,
    )
