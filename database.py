import os
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from utils.logging_config import get_logger
from sqlalchemy.engine import Engine
from sqlalchemy import event
import sqlite3

logger = get_logger(__name__)

# Database path (relative to the project root)
DB_PATH = "sqlite:///dnd_bot.db"

# Create engine
logger.debug(f"Connecting to database at {DB_PATH}")
engine = create_engine(DB_PATH)

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
