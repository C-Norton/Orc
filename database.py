import os
import sqlite3
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from utils.logging_config import get_logger

logger = get_logger(__name__)

# Use DATABASE_URL from the environment (set in production via /etc/orc-bot.env),
# falling back to a local SQLite file for development.
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///dnd_bot.db")

# Create engine
engine = create_engine(DATABASE_URL)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Log with the password masked to avoid writing credentials to disk.
logger.debug(
    f"Connecting to database at {engine.url.render_as_string(hide_password=True)}"
)


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record) -> None:
    """Enable foreign key enforcement for SQLite connections.

    SQLite disables foreign key checks by default; this hook turns them on
    each time a connection is opened.  The ``isinstance`` guard ensures the
    pragma is only sent to SQLite — PostgreSQL connections are left untouched.
    ``connection_record`` is part of the SQLAlchemy event signature and is not
    used here.
    """
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


@contextmanager
def db_session() -> Generator[Session, None, None]:
    """Provide a database session and guarantee it is closed on exit.

    Usage::

        with db_session() as db:
            ...
            db.commit()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
