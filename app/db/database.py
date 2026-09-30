"""SQLAlchemy database engine, session factory, and Base class.

Usage
-----
Import `get_db` as a FastAPI dependency to obtain a scoped session::

    from app.db.database import get_db
    from sqlalchemy.orm import Session

    def my_endpoint(db: Session = Depends(get_db)):
        ...

Import `Base` in every ORM model module so Alembic can discover them via
`target_metadata` in `alembic/env.py`.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

# ── Engine ───────────────────────────────────────────────────────────────────

# SQLite requires check_same_thread=False; Postgres does not need it.
_connect_args: dict = {}
if settings.SQLALCHEMY_DATABASE_URI.startswith("sqlite"):
    _connect_args["check_same_thread"] = False

engine = create_engine(
    settings.SQLALCHEMY_DATABASE_URI,
    connect_args=_connect_args,
    # Validate connections before handing them out from the pool.
    pool_pre_ping=True,
    # Disable SQLAlchemy-level query echoing; set to True only for debugging.
    echo=False,
)

# ── Session Factory ───────────────────────────────────────────────────────────

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    # Prevent lazy-loading errors after commit by not expiring objects.
    expire_on_commit=False,
)


# ── Declarative Base ──────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    """Shared declarative base for all ORM models.

    Import this in every model file to register it with Alembic's
    ``target_metadata``.
    """

    pass


# ── FastAPI Dependency ────────────────────────────────────────────────────────

def get_db() -> Generator[Session, None, None]:
    """Yield a database session and ensure it is closed after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
