"""DiagnosticCentre data access layer."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.centre import DiagnosticCentre
from app.models.centre_test import CentreTest
from app.schemas.centre import CentreCreate, CentreUpdate
from app.schemas.centre_test import CentreTestCreate


class CentreRepository:
    """Repository handling database operations for diagnostic centres and centre tests."""

    @staticmethod
    def get_by_id(db: Session, centre_id: int) -> DiagnosticCentre | None:
        """Fetch a centre by ID or return None."""
        return db.scalar(select(DiagnosticCentre).where(DiagnosticCentre.id == centre_id))

    @staticmethod
    def list_centres(
        db: Session,
        city: str | None = None,
        is_active: bool | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[DiagnosticCentre]:
        """Query centres with optional city and active status filtering and pagination."""
        query = select(DiagnosticCentre)
        if city:
            query = query.where(DiagnosticCentre.city.ilike(f"%{city.strip()}%"))
        if is_active is not None:
            query = query.where(DiagnosticCentre.is_active == is_active)
        return db.scalars(query.offset(skip).limit(limit)).all()

    @staticmethod
    def create(db: Session, centre_in: CentreCreate) -> DiagnosticCentre:
        """Create and persist a new diagnostic centre."""
        centre = DiagnosticCentre(
            name=centre_in.name.strip(),
            address=centre_in.address.strip(),
            city=centre_in.city.strip(),
            state=centre_in.state.strip(),
            latitude=centre_in.latitude,
            longitude=centre_in.longitude,
            is_active=centre_in.is_active,
        )
        db.add(centre)
        db.commit()
        db.refresh(centre)
        return centre

    @staticmethod
    def update(db: Session, centre: DiagnosticCentre, centre_in: CentreUpdate) -> DiagnosticCentre:
        """Update existing diagnostic centre fields."""
        update_data = centre_in.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if isinstance(value, str):
                value = value.strip()
            setattr(centre, field, value)
        db.commit()
        db.refresh(centre)
        return centre

    @staticmethod
    def get_centre_test(db: Session, centre_id: int, test_id: int) -> CentreTest | None:
        """Look up a specific centre-test association."""
        return db.scalar(
            select(CentreTest)
            .where(CentreTest.centre_id == centre_id, CentreTest.test_id == test_id)
            .options(selectinload(CentreTest.test))
        )

    @staticmethod
    def get_centre_test_by_id(db: Session, centre_test_id: int) -> CentreTest | None:
        """Look up a centre-test association by its primary key."""
        return db.scalar(
            select(CentreTest)
            .where(CentreTest.id == centre_test_id)
            .options(selectinload(CentreTest.test), selectinload(CentreTest.centre))
        )

    @staticmethod
    def list_centre_tests(
        db: Session, centre_id: int, is_available: bool | None = None
    ) -> Sequence[CentreTest]:
        """List all tests offered at a centre with their centre-specific pricing."""
        query = (
            select(CentreTest)
            .where(CentreTest.centre_id == centre_id)
            .options(selectinload(CentreTest.test))
        )
        if is_available is not None:
            query = query.where(CentreTest.is_available == is_available)
        return db.scalars(query).all()

    @staticmethod
    def add_centre_test(
        db: Session, centre_id: int, centre_test_in: CentreTestCreate
    ) -> CentreTest:
        """Associate a diagnostic test with a centre at a given price."""
        centre_test = CentreTest(
            centre_id=centre_id,
            test_id=centre_test_in.test_id,
            price=centre_test_in.price,
            is_available=centre_test_in.is_available,
        )
        db.add(centre_test)
        db.commit()
        db.refresh(centre_test)
        # Fetch with loaded test relationship
        return CentreRepository.get_centre_test(db, centre_id, centre_test_in.test_id) or centre_test
