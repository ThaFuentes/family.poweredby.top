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
        from app.builddb.table_users import User

        return User.query.filter_by(id=int(user_id), is_active=True).first()
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
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_recycle": 280,
        "pool_pre_ping": True,
        "pool_size": 5,
        "max_overflow": 10,
        "pool_timeout": 30,
        "connect_args": {
            "connect_timeout": 15,
            "read_timeout": 30,
            "write_timeout": 30,
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
        return {
            "SITE_MODE": "family",
            "SITE_NAME": "Family OS",
            "household_name": household_name,
            "can": _can,
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
