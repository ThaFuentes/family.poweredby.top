# ================================================================
# family.poweredby.top — HOUSEHOLD OS
# Multi-tenant (household_id on every row). Scan is the truth event.
# ================================================================
import os
from flask import Flask
from flask_login import LoginManager
from dotenv import load_dotenv

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Sign in to open your household."
login_manager.login_message_category = "info"


@login_manager.user_loader
def load_user(user_id):
    try:
        from sqlalchemy.orm import joinedload

        from app.builddb.table_users import User

        return (
            User.query.options(joinedload(User.household))
            .filter_by(id=int(user_id), is_active=True)
            .first()
        )
    except Exception:
        return None


def create_app():
    load_dotenv()
    app = Flask(
        __name__,
        instance_relative_config=True,
        static_folder="static",
        template_folder="templates",
    )
    app.config["SITE_MODE"] = "family"
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
    if not app.config["SECRET_KEY"]:
        raise ValueError("SECRET_KEY is not set in your .env file!")
    try:
        app.config["MAX_CONTENT_LENGTH"] = int(
            os.getenv("UPLOAD_MAX_BYTES") or str(20 * 1024 * 1024)
        )
    except Exception:
        app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024

    from dbconnector import DATABASE_URI

    app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URI
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    # Versioned /static/* URLs (?v=os19). Browsers keep CSS/JS/images a week.
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 604800
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_recycle": 280,
        "pool_pre_ping": True,
        "pool_size": 5,
        "max_overflow": 10,
        "pool_timeout": 30,
        "connect_args": {
            "connect_timeout": 15,
            "read_timeout": 90,
            "write_timeout": 90,
        },
        "pool_reset_on_return": "commit",
    }
    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(os.path.join(os.path.dirname(app.root_path), "uploads"), exist_ok=True)

    try:
        from poweredbytop import init_security

        init_security(app)
    except Exception as e:
        try:
            app.logger.exception("init_security failed (app still starts): %s", e)
        except Exception:
            print(f"init_security failed (app still starts): {e}")

    from app.builddb.builddb import init_tenant_system

    init_tenant_system(app)
    login_manager.init_app(app)

    from werkzeug.middleware.proxy_fix import ProxyFix

    # Tailscale Serve (and HostM) terminate TLS and forward HTTP.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.config["PREFERRED_URL_SCHEME"] = os.getenv("PREFERRED_URL_SCHEME") or "https"

    @app.context_processor
    def _site_ctx():
        from flask_login import current_user
        from app.utils.permissions import can as _can

        household_name = None
        try:
            if getattr(current_user, "is_authenticated", False):
                household_name = getattr(getattr(current_user, "household", None), "name", None)
        except Exception:
            household_name = None
        from app.utils.scan import qty_label as _qty_label
        from app.utils.themes import read_theme, THEMES
        from app.utils.places import list_places as _list_places
        from app.utils.permissions import role_of as _role_of

        theme_id = read_theme()
        places = []
        hh = getattr(current_user, "household", None) if getattr(current_user, "is_authenticated", False) else None
        if hh is not None:
            try:
                places = _list_places(hh)
            except Exception:
                places = []
        return {
            "SITE_MODE": "family",
            "SITE_NAME": "Family OS",
            "household_name": household_name,
            "can": _can,
            "qty_label": _qty_label,
            "current_theme": theme_id,
            "theme_color": THEMES[theme_id]["color"],
            "places": places,
            "is_child": _role_of() == "child" if getattr(current_user, "is_authenticated", False) else False,
        }

    from app.routes.auth import auth_bp
    from app.routes.home import home_bp
    from app.routes.scan import scan_bp
    from app.routes.groceries import groceries_bp
    from app.routes.tools import tools_bp
    from app.routes.vehicles import vehicles_bp
    from app.routes.reminders import reminders_bp
    from app.routes.items import items_bp
    from app.routes.members import members_bp
    from app.routes.api import api_bp
    from app.routes.appearance import appearance_bp
    from app.routes.notes import notes_bp
    from app.routes.platform import platform_bp
    from app.routes.find import find_bp
    from app.routes.house import house_bp
    from app.routes.legal import legal_bp
    from app.routes.sort import sort_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(home_bp)
    app.register_blueprint(scan_bp)
    app.register_blueprint(groceries_bp)
    app.register_blueprint(tools_bp)
    app.register_blueprint(vehicles_bp)
    app.register_blueprint(reminders_bp)
    app.register_blueprint(items_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(appearance_bp)
    app.register_blueprint(notes_bp)
    app.register_blueprint(platform_bp)
    app.register_blueprint(find_bp)
    app.register_blueprint(house_bp)
    app.register_blueprint(legal_bp)
    app.register_blueprint(sort_bp)

    @app.before_request
    def _block_paused_household():
        from flask import request, flash, redirect, url_for
        from flask_login import current_user, logout_user

        if not getattr(current_user, "is_authenticated", False):
            return None
        path = request.path or ""
        if path.startswith("/platform") or path.startswith("/static") or path.startswith("/auth/logout"):
            return None
        try:
            h = getattr(current_user, "household", None)
            if h is not None and not bool(getattr(h, "is_active", True)):
                logout_user()
                flash("This household is paused. Ask the household leader.", "warning")
                return redirect(url_for("auth.login"))
        except Exception:
            return None
        return None

    try:
        from app.utils.favicon_inject import register_favicon

        register_favicon(app)
    except Exception as e:
        app.logger.error("favicon inject failed: %s", e)

    try:
        from app.utils.pwa import register_pwa

        register_pwa(app)
    except Exception as e:
        app.logger.error("pwa register failed: %s", e)

    @app.after_request
    def _cache_static(response):
        try:
            from flask import request

            path = request.path or ""
            if path.startswith("/static/"):
                response.headers["Cache-Control"] = "public, max-age=604800, immutable"
        except Exception:
            pass
        return response

    @app.route("/healthz")
    def healthz():
        return {"ok": True, "site": "family"}, 200

    @app.errorhandler(403)
    def _forbidden(_e):
        from flask import render_template

        return render_template("error.html", code=403, message="You cannot do that in this household."), 403

    @app.errorhandler(404)
    def _not_found(_e):
        from flask import render_template

        return render_template("error.html", code=404, message="That page is not in this household."), 404

    return app
