from flask import Blueprint

security_bp = Blueprint("security", __name__, url_prefix="/security")

from . import views  # noqa: E402,F401

try:
    from . import threat_map  # noqa: E402,F401
except Exception as exc:
    print(f"[security] threat_map not loaded: {exc}")

__all__ = ["security_bp"]
