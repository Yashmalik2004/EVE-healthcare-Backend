"""AppointmentSlot business logic service layer."""

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictException, NotFoundException, ValidationException
from app.core.logging import logger
from app.models.appointment_slot import AppointmentSlot
from app.repositories.centre_repository import CentreRepository
from app.repositories.slot_repository import SlotRepository
from app.schemas.slot import SlotCreate


class SlotService:
    """Service handling appointment slot creation, listing, and concurrent reservation."""

    def __init__(
        self,
        slot_repo: type[SlotRepository] = SlotRepository,
        centre_repo: type[CentreRepository] = CentreRepository,
    ):
        self.slot_repo = slot_repo
        self.centre_repo = centre_repo

    def create_slot(
        self, db: Session, centre_id: int, slot_in: SlotCreate
    ) -> AppointmentSlot:
        """Create a new appointment slot for a diagnostic centre.

        Validations:
        - Centre exists and is active.
        - Appointment datetime is in the future and converted to UTC.
        - centre_test_id (if provided) exists and belongs to the centre.
        - No duplicate slot exists at the same centre for the exact same datetime and test.
        """
        centre = self.centre_repo.get_by_id(db, centre_id)
        if not centre:
            logger.warning(f"Failed to create slot: centre id={centre_id} not found")
            raise NotFoundException("DiagnosticCentre", centre_id)

        if not centre.is_active:
            raise ValidationException("INACTIVE_CENTRE", "Cannot create appointment slot at an inactive centre.")

        # Normalize datetime to UTC
        slot_dt = slot_in.appointment_datetime
        if slot_dt.tzinfo is None:
            slot_dt = slot_dt.replace(tzinfo=UTC)
        else:
            slot_dt = slot_dt.astimezone(UTC)

        now_utc = datetime.now(UTC)
        if slot_dt <= now_utc:
            logger.warning(f"Past slot datetime rejected: {slot_dt} <= {now_utc}")
            raise ValidationException(
                "PAST_APPOINTMENT_DATE",
                "Appointment slot time must be in the future.",
            )

        if slot_in.centre_test_id is not None:
            ct = self.centre_repo.get_centre_test_by_id(db, slot_in.centre_test_id)
            if not ct or ct.centre_id != centre_id:
                raise ValidationException(
                    "INVALID_CENTRE_TEST",
                    "The specified centre test does not belong to this centre.",
                )

        # Check for duplicate slot
        existing = self.slot_repo.get_by_centre_and_datetime(
            db, centre_id=centre_id, dt=slot_dt, centre_test_id=slot_in.centre_test_id
        )
        if existing:
            logger.warning(
                f"Duplicate slot rejected for centre {centre_id} at {slot_dt}"
            )
            raise ConflictException(
                "DUPLICATE_APPOINTMENT_SLOT",
                "An appointment slot already exists at this centre for the specified time.",
            )

        logger.info(f"Creating appointment slot for centre id={centre_id} at {slot_dt}")
        return self.slot_repo.create(
            db,
            centre_id=centre_id,
            slot_in=slot_in,
            appointment_datetime_utc=slot_dt,
        )

    def list_slots(
        self,
        db: Session,
        centre_id: int,
        is_available: bool | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[AppointmentSlot]:
        """List slots for a centre with availability filter and pagination."""
        centre = self.centre_repo.get_by_id(db, centre_id)
        if not centre:
            logger.warning(f"Failed to list slots: centre id={centre_id} not found")
            raise NotFoundException("DiagnosticCentre", centre_id)

        return self.slot_repo.list_slots(
            db,
            centre_id=centre_id,
            is_available=is_available,
            skip=skip,
            limit=limit,
        )

    def reserve_slot_concurrency_safe(
        self, db: Session, slot_id: int
    ) -> AppointmentSlot:
        """Lock and safely reserve an appointment slot using SELECT ... FOR UPDATE.

        Prepared for Phase 6 concurrent booking reservations to eliminate race conditions.
        """
        slot = self.slot_repo.get_slot_for_update(db, slot_id)
        if not slot:
            raise NotFoundException("AppointmentSlot", slot_id)

        if not slot.is_available:
            raise ConflictException(
                "SLOT_ALREADY_RESERVED",
                "Appointment slot is already reserved and no longer available.",
            )

        slot.is_available = False
        db.commit()
        db.refresh(slot)
        return slot


slot_service = SlotService()
