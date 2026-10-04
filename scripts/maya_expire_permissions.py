"""Cron: switch off Maya permissions whose auto-off timer has passed.

The API already treats an expired switch as OFF on every call (and flips it
lazily); this makes the page and audit log tidy even when Maya is idle.

    */15 * * * * cd /path/to/family.poweredby.top && .venv/bin/python scripts/maya_expire_permissions.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from app import create_app  # noqa: E402
from app.utils import maya_perms  # noqa: E402

if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        n = maya_perms.expire_due()
    print(f"maya permissions auto-expired: {n}")
