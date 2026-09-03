from functools import wraps
from flask import abort, flash, redirect, url_for
from flask_login import current_user

# Child: scan only. Member: scan + groceries + maintenance + photos.
# Admin: full control including metadata and members.
ROLE_PERMS = {
    "child": frozenset({"scan", "view"}),
    "member": frozenset({"scan", "view", "edit_grocery", "maintain", "photo"}),
    "admin": frozenset(
        {
            "scan",
            "view",
            "edit_grocery",
            "maintain",
            "photo",
            "edit_meta",
            "members",
            "settings",
        }
    ),
}


def role_of(user=None) -> str:
    u = user if user is not None else current_user
    return (getattr(u, "role", None) or "").strip().lower()


def can(action: str, user=None) -> bool:
    u = user if user is not None else current_user
    if not getattr(u, "is_authenticated", False):
        return False
    extra = getattr(u, "permissions_json", None) or {}
    if isinstance(extra, dict) and extra.get(action) is True:
        return True
    if extra.get(action) is False:
        return False
    return action in ROLE_PERMS.get(role_of(u), frozenset())


def require_perm(action: str):
    def deco(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not getattr(current_user, "is_authenticated", False):
                return redirect(url_for("auth.login"))
            if not can(action):
                flash("You do not have permission to do that.", "warning")
                abort(403)
            return fn(*args, **kwargs)

        return wrapped

    return deco
