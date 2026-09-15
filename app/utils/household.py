from flask import abort
from flask_login import current_user


def household_id() -> int:
    if not getattr(current_user, "is_authenticated", False):
        abort(401)
    hid = getattr(current_user, "household_id", None)
    if not hid:
        abort(403)
    return int(hid)


def scoped(model, include_removed=False):
    """Every list query is household-scoped. Never skip this."""
    q = model.query.filter_by(household_id=household_id())
    if not include_removed and getattr(model, "removed_at", None) is not None:
        q = q.filter(model.removed_at.is_(None))
    return q


def get_or_404(model, ident, id_field="id"):
    q = scoped(model).filter(getattr(model, id_field) == ident)
    row = q.first()
    if row is None:
        abort(404)
    return row
