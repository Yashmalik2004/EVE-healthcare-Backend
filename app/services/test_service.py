"""DiagnosticTest business logic service layer."""

from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundException
from app.core.logging import logger
from app.models.diagnostic_test import DiagnosticTest
from app.repositories.test_repository import TestRepository
from app.schemas.diagnostic_test import DiagnosticTestCreate


class TestService:
    """Service orchestrating diagnostic test catalogue operations."""

    def __init__(self, test_repo: type[TestRepository] = TestRepository):
        self.test_repo = test_repo

    def get_test(self, db: Session, test_id: int) -> DiagnosticTest:
        """Retrieve test by ID or raise NotFoundException."""
        test = self.test_repo.get_by_id(db, test_id)
        if not test:
            logger.warning(f"Diagnostic test id={test_id} not found")
            raise NotFoundException("DiagnosticTest", test_id)
        return test

    def list_tests(
        self,
        db: Session,
        category: str | None = None,
        is_active: bool | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[DiagnosticTest]:
        """List diagnostic tests with optional category and active filtering and pagination."""
        return self.test_repo.list_tests(
            db, category=category, is_active=is_active, skip=skip, limit=limit
        )

    def create_test(self, db: Session, test_in: DiagnosticTestCreate) -> DiagnosticTest:
        """Create a new diagnostic test."""
        logger.info(f"Creating diagnostic test: '{test_in.name}' in category '{test_in.category}'")
        return self.test_repo.create(db, test_in)


test_service = TestService()
