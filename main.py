# Production entry is passenger_wsgi.py. HostM / Passenger owns the socket
# and never runs the block at the bottom. This file may still export
# `application` if a WSGI server imports it — that does not pick a port.
#
# `python main.py` is laptop-only (start_local.sh). Default 5060 avoids
# colliding with aegis/ax on :5000. Not a HostM listener.

import os
import sys
from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from app import create_app

# create_app() already calls init_security once (SITE_MODE is set first).
app = create_app()
application = app


def _dev_flag() -> bool:
    return os.getenv("DEBUG_MODE", "").strip().lower() in ("1", "true", "yes", "on") or os.getenv(
        "AEGIS_DEV", ""
    ).strip().lower() in ("1", "true", "yes", "on")


if __name__ == "__main__":
    if not _dev_flag():
        sys.exit(
            "Refusing to bind a port. Production is passenger_wsgi.py "
            "(HostM chooses the socket). Laptop: DEBUG_MODE=true python main.py"
        )
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5060"))
    print(f"Laptop dev server {host}:{port} — not used on HostM")
    app.run(host=host, port=port, debug=True, use_reloader=False)
