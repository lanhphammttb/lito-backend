import os
from sqlmodel import create_engine, Session, SQLModel
from sqlalchemy.exc import OperationalError
from sqlalchemy import text as sa_text
from sqlalchemy.pool import StaticPool
from pymongo import MongoClient
from app.core.config import DATABASE_URL, MONGO_URL

# --- MongoDB Setup ---
MONGO_CLIENT = None
MONGO_DB = None
if MONGO_URL:
    try:
        MONGO_CLIENT = MongoClient(MONGO_URL, serverSelectionTimeoutMS=2000)
        MONGO_CLIENT.admin.command('ping')
        # Extract DB name from URL or default to 'halahandmade'
        db_name = MONGO_URL.split('/')[-1].split('?')[0]
        if not db_name or db_name == MONGO_URL:
            db_name = 'halahandmade'
        MONGO_DB = MONGO_CLIENT[db_name]
        print(f"[DB] Connected to MongoDB: {db_name}")
    except Exception as e:
        print(f"[DB] Failed to connect to MongoDB: {e}")
        MONGO_CLIENT = None
        MONGO_DB = None

# --- SQL Database Setup ---
SQL_INITIALIZED = False

# Default to local SQLite if no DB URL is provided
if not DATABASE_URL:
    DATABASE_URL = "sqlite:///./db.sqlite"

try:
    connect_args = {}
    pool_config = {}

    if DATABASE_URL.startswith("sqlite"):
        # SQLite needs check_same_thread=False for FastAPI concurrency
        connect_args["check_same_thread"] = False
    elif DATABASE_URL.startswith("postgres"):
        # Optimizations for Supabase/Postgres
        connect_args["connect_timeout"] = int(os.getenv("PG_CONNECT_TIMEOUT", "10"))
        connect_args["keepalives"] = 1
        connect_args["keepalives_idle"] = 30
        connect_args["keepalives_interval"] = 10
        connect_args["keepalives_count"] = 5

        pool_config = {
            "pool_size": 10,
            "max_overflow": 20,
            "pool_timeout": 30,
            "pool_recycle": 3600,
            "pool_pre_ping": True,
        }
    else:
        pool_config["pool_pre_ping"] = True

    engine = create_engine(
        DATABASE_URL,
        echo=False,
        connect_args=connect_args if connect_args else {},
        **pool_config
    )

    # Test connection
    with engine.connect() as conn:
        conn.execute(sa_text("SELECT 1"))

    # Only set up engine here, schemas will call create_all() later in main.py
    # SQLModel.metadata.create_all(engine)
    SQL_INITIALIZED = True
    print(f"[DB] Connected to SQL DB: {DATABASE_URL.split('://')[0]}")

except (OperationalError, Exception) as e:
    print(f"[DB] Failed to connect to SQL: {e}")
    print(f"[DB] Fallback to in-memory mode")
    DATABASE_URL = "sqlite:///:memory:"
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    SQL_INITIALIZED = True
    print(f"[DB] In-memory SQLite initialized")

# Dependency for API Routes
def get_db():
    with Session(engine) as session:
        yield session
