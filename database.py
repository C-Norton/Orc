import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Database path (relative to the project root)
DB_PATH = "sqlite:///dnd_bot.db"

# Create engine
engine = create_engine(DB_PATH)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
