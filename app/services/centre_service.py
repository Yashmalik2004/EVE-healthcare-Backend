"""DiagnosticCentre business logic service layer."""

from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictException, NotFoundException, ValidationException
from app.core.logging import logger
from app.models.centre import DiagnosticCentre
from app.models.centre_test import CentreTest
from app.repositories.centre_repository import CentreRepository
from app.repositories.test_repository import TestRepository
from app.schemas.centre import CentreCreate, CentreUpdate
from app.schemas.centre_test import CentreTestCreate


class CentreService:
    """Service orchestrating diagnostic centre and centre-test association operations."""

    def __init__(
        self,
        centre_repo: type[CentreRepository] = CentreRepository,
        test_repo: type[TestRepository] = TestRepository,
    ):
        self.centre_repo = centre_repo
        self.test_repo = test_repo

    def get_centre(self, db: Session, centre_id: int) -> DiagnosticCentre:
        """Retrieve centre by ID or raise NotFoundException."""
        centre = self.centre_repo.get_by_id(db, centre_id)
        if not centre:
            logger.warning(f"Diagnostic centre id={centre_id} not found")
            raise NotFoundException("DiagnosticCentre", centre_id)
        return centre

    def list_centres(
        self,
        db: Session,
        city: str | None = None,
        is_active: bool | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[DiagnosticCentre]:
        """List diagnostic centres with optional filters and pagination."""
        return self.centre_repo.list_centres(
            db, city=city, is_active=is_active, skip=skip, limit=limit
        )

    def create_centre(self, db: Session, centre_in: CentreCreate) -> DiagnosticCentre:
        """Create a new diagnostic centre."""
        logger.info(f"Creating diagnostic centre: '{centre_in.name}' in '{centre_in.city}'")
        return self.centre_repo.create(db, centre_in)

    def update_centre(
        self, db: Session, centre_id: int, centre_in: CentreUpdate
    ) -> DiagnosticCentre:
        """Update an existing diagnostic centre."""
        centre = self.get_centre(db, centre_id)
        logger.info(f"Updating diagnostic centre id={centre_id}")
        return self.centre_repo.update(db, centre, centre_in)

    def add_test_to_centre(
        self, db: Session, centre_id: int, centre_test_in: CentreTestCreate
    ) -> CentreTest:
        """Associate a diagnostic test with a centre at a centre-specific price.

        Validates:
        - Centre exists and is active.
        - Test exists and is active.
        - Price is valid and positive.
        - Association does not already exist (no duplicates).
        """
        centre = self.get_centre(db, centre_id)
        if not centre.is_active:
            raise ValidationException("INACTIVE_CENTRE", "Cannot add tests to an inactive centre.")

        test = self.test_repo.get_by_id(db, centre_test_in.test_id)
        if not test:
            logger.warning(f"Diagnostic test id={centre_test_in.test_id} not found")
            raise NotFoundException("DiagnosticTest", centre_test_in.test_id)
        if not test.is_active:
            raise ValidationException("INACTIVE_TEST", "Cannot add an inactive test to a centre.")

        if centre_test_in.price <= Decimal("0.00"):
            raise ValidationException("INVALID_PRICE", "Test price must be greater than zero.")

        existing = self.centre_repo.get_centre_test(db, centre_id, centre_test_in.test_id)
        if existing:
            logger.warning(
                f"Duplicate centre test: centre {centre_id} already has test {centre_test_in.test_id}"
            )
            raise ConflictException(
                "DUPLICATE_CENTRE_TEST",
                "This diagnostic test is already configured for this centre.",
            )

        logger.info(
            f"Configuring test id={centre_test_in.test_id} at centre id={centre_id} "
            f"for price={centre_test_in.price}"
        )
        return self.centre_repo.add_centre_test(db, centre_id, centre_test_in)

    def list_centre_tests(
        self, db: Session, centre_id: int, is_available: bool | None = None
    ) -> Sequence[CentreTest]:
        """List all tests offered at a centre with their centre-specific pricing."""
        self.get_centre(db, centre_id)  # Validate centre exists
        return self.centre_repo.list_centre_tests(db, centre_id, is_available=is_available)


centre_service = CentreService()
