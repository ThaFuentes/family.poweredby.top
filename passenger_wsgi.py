# passenger_wsgi.py — family.poweredby.top
# Loads .env WITHOUT requiring python-dotenv (avoids blank 500 if dotenv missing)
import os
import sys

# HARD RULE: never encode logs as ASCII. UTF-8 only. See AGENTS.md.
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _load_env_file(path):
    """Minimal KEY=VALUE loader. No pip package needed."""
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
                if key in ("MASTER_KEY", "SECRET_KEY", "MYSQL_PASSWORD") and val:
                    os.environ[key] = val
    except Exception:
        pass


_load_env_file(os.path.join(ROOT, ".env"))

try:
    from app import create_app

    # create_app() already calls init_security once. Do not call it again —
    # duplicate before_request hooks double DB/rate-limit work per request.
    app = create_app()
    application = app
    print("Passenger WSGI loaded successfully - family.poweredby.top ready")
except Exception:
    err_path = os.path.join(ROOT, "tmp", "wsgi_error.log")
    try:
        os.makedirs(os.path.dirname(err_path), exist_ok=True)
        with open(err_path, "a") as f:
            f.write("\n===== WSGI BOOT FAILURE =====\n")
            traceback.print_exc(file=f)
            f.write(
                "\nMASTER_KEY set: %s\nSECRET_KEY set: %s\nMYSQL_DATABASE: %s\n"
                % (
                    "yes" if os.environ.get("MASTER_KEY") else "NO",
                    "yes" if os.environ.get("SECRET_KEY") else "NO",
                    os.environ.get("MYSQL_DATABASE", ""),
                )
            )
    except Exception:
        pass
    traceback.print_exc()
    raise
