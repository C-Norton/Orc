import os
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from utils.logging_config import get_logger
from sqlalchemy.engine import Engine
from sqlalchemy import event
import sqlite3

logger = get_logger(__name__)

# Use DATABASE_URL from the environment (set in production via /etc/orc-bot.env),
# falling back to a local SQLite file for development.
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///dnd_bot.db")

# Create engine
logger.debug(f"Connecting to database at {DATABASE_URL}")
engine = create_engine(DATABASE_URL)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
