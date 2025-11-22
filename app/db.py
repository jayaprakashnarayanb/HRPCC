# app/db.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, scoped_session
import os

# Prefer env var, then Render Disk at /data, then local file.
def _default_db_url() -> str:
    if os.getenv("DATABASE_URL"):
        return os.getenv("DATABASE_URL")
    # If a Render Disk is mounted at /data, use it
    if os.path.isdir("/data"):
        return "sqlite:////data/hr_compliance.db"
    # Fallback to local project path
    return "sqlite:///hr_compliance.db"


DATABASE_URL = _default_db_url()

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)

SessionLocal = scoped_session(
    sessionmaker(autocommit=False, autoflush=False, bind=engine)
)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
