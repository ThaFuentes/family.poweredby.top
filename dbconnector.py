# ===========================================================
# File: dbconnector.py (project root)
# Purpose: Stable MariaDB connector for family.poweredby.top
# Hardened against "Commands Out of Sync", stale connections,
# and cPanel/HostM long-idle issues.
# ===========================================================
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.pool import Pool

load_dotenv()

MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = os.getenv("MYSQL_PORT", "3306")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE")

if not all([MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE]):
    raise RuntimeError("Missing MYSQL_* variables in .env")

DATABASE_URI = (
    f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@"
    f"{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}"
)

print("DATABASE_URI successfully built from .env MYSQL_* variables")
print(f" Host: {MYSQL_HOST}:{MYSQL_PORT} | DB: {MYSQL_DATABASE} | User: {MYSQL_USER}")

engine = create_engine(
    DATABASE_URI,
    pool_pre_ping=True,
    pool_recycle=120,
    pool_size=20,
    max_overflow=30,
    pool_timeout=45,
    pool_reset_on_return="commit",
    echo=False,
    connect_args={
        "charset": "utf8mb4",
        "connect_timeout": 20,
        "read_timeout": 45,
        "write_timeout": 45,
        "autocommit": False,
    },
    execution_options={"isolation_level": "READ COMMITTED"},
)


@event.listens_for(Pool, "checkout")
def _on_checkout(dbapi_conn, connection_rec, connection_proxy):
    try:
        cursor = dbapi_conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        cursor.close()
    except Exception:
        connection_rec.invalidate()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_engine():
    return engine


def reset_connection_pool():
    global engine, SessionLocal
    try:
        engine.dispose()
        engine = create_engine(
            DATABASE_URI,
            pool_pre_ping=True,
            pool_recycle=120,
            pool_size=20,
            max_overflow=30,
            pool_timeout=45,
            pool_reset_on_return="commit",
            echo=False,
            connect_args={
                "charset": "utf8mb4",
                "connect_timeout": 20,
                "read_timeout": 45,
                "write_timeout": 45,
                "autocommit": False,
            },
            execution_options={"isolation_level": "READ COMMITTED"},
        )
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        print("[DBCONNECTOR] Connection pool has been fully reset.")
    except Exception as e:
        print(f"[DBCONNECTOR ERROR] Failed to reset pool: {e}")


def init_db(app):
    app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URI
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": 120,
        "pool_size": 20,
        "max_overflow": 30,
        "pool_timeout": 45,
        "pool_reset_on_return": "commit",
    }
    app.config["SQLALCHEMY_ENGINE"] = engine


print(
    "dbconnector.py fully loaded - STABLE pool settings "
    "(recycle=120 + pre_ping + reset_on_return + checkout listener)"
)
