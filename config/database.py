"""Database connection and session management."""
import os
from typing import Generator, Optional
from sqlmodel import SQLModel, Session, create_engine
from contextlib import contextmanager

from .settings import DATABASE_URL, USE_MONGO

# Create engine
connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, echo=False, pool_pre_ping=True)


# MongoDB connection (optional)
mongo_db = None
mongo_client = None
if USE_MONGO:
    try:
        from pymongo import MongoClient
        mongo_client = MongoClient(os.getenv("MONGO_URL", "mongodb://localhost:27017"))
        mongo_db = mongo_client["hala_handmade"]
    except Exception as e:
        print(f"MongoDB connection failed: {e}")
        mongo_db = None


def upsert_mongo(collection: str, doc: dict, key_field: str = "id"):
    """Ghi document vào MongoDB nếu kết nối được (dual-write helper)."""
    if mongo_db is None:
        return
    try:
        key_val = doc.get(key_field)
        if key_val is None:
            return
        mongo_db[collection].replace_one({key_field: key_val}, doc, upsert=True)
    except Exception as exc:
        print(f"[Mongo] upsert {collection} failed: {exc}")


def delete_mongo(collection: str, key_field: str, key_val):
    """Xóa document khỏi MongoDB."""
    if mongo_db is None:
        return
    try:
        mongo_db[collection].delete_one({key_field: key_val})
    except Exception as exc:
        print(f"[Mongo] delete {collection} failed: {exc}")


def close_mongo_connection():
    """Close the optional Mongo client cleanly."""
    global mongo_client, mongo_db
    if mongo_client is not None:
        mongo_client.close()
        mongo_client = None
        mongo_db = None


def create_db_and_tables():
    """Create all database tables."""
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    """Get database session dependency."""
    with Session(engine) as session:
        yield session


@contextmanager
def get_db_session():
    """Context manager for database session."""
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
