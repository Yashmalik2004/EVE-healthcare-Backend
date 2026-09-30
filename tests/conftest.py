"""Pytest configuration and shared fixtures for the EVE Healthcare Backend test suite.

Strategy
--------
* A fresh SQLite in-memory database is created once per session via ``setup_test_db``.
* Each test gets a transaction-scoped database session that is rolled back after the
  test, ensuring full isolation without recreating the schema for every test.
* The ``client`` fixture wires the test session into FastAPI's dependency injection
  system, so endpoint code runs against the in-memory database transparently.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.main import app

# ── Test Database ─────────────────────────────────────────────────────────────

SQLALCHEMY_TEST_DATABASE_URL = "sqlite:///:memory:"

engine_test = create_engine(
    SQLALCHEMY_TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine_test)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    """Create all tables once at the start of the test session; drop them at the end."""
    Base.metadata.create_all(bind=engine_test)
    yield
    Base.metadata.drop_all(bind=engine_test)


@pytest.fixture
def db():
    """Yield a transactional session that is rolled back after each test."""
    connection = engine_test.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(db):
    """Yield a FastAPI TestClient using the in-memory test database session."""

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
