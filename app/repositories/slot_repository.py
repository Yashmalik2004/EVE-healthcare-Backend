"""AppointmentSlot data access layer."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.appointment_slot import AppointmentSlot
from app.schemas.slot import SlotCreate


class SlotRepository:
    """Repository handling database persistence and concurrency locking for appointment slots."""

    @staticmethod
    def get_by_id(db: Session, slot_id: int) -> AppointmentSlot | None:
        """Fetch an appointment slot by primary key."""
        return db.scalar(select(AppointmentSlot).where(AppointmentSlot.id == slot_id))

    @staticmethod
    def get_slot_for_update(db: Session, slot_id: int) -> AppointmentSlot | None:
        """Fetch slot with row-level lock (SELECT ... FOR UPDATE) for safe concurrent reservation.

        Prepares the slot subsystem for Phase 6 concurrent booking reservations,
        preventing double-booking race conditions under high traffic.
        """
        return db.scalar(
            select(AppointmentSlot)
            .where(AppointmentSlot.id == slot_id)
            .with_for_update()
        )

    @staticmethod
    def get_by_centre_and_datetime(
        db: Session, centre_id: int, dt: datetime, centre_test_id: int | None = None
    ) -> AppointmentSlot | None:
        """Check for existing slot with identical centre, datetime, and centre_test."""
        query = select(AppointmentSlot).where(
            AppointmentSlot.centre_id == centre_id,
            AppointmentSlot.appointment_datetime == dt,
        )
        if centre_test_id is not None:
            query = query.where(AppointmentSlot.centre_test_id == centre_test_id)
        else:
            query = query.where(AppointmentSlot.centre_test_id.is_(None))
        return db.scalar(query)

    @staticmethod
    def list_slots(
        db: Session,
        centre_id: int,
        is_available: bool | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[AppointmentSlot]:
        """List appointment slots belonging to a specific centre with filtering and pagination."""
        query = (
            select(AppointmentSlot)
            .where(AppointmentSlot.centre_id == centre_id)
            .order_by(AppointmentSlot.appointment_datetime.asc())
        )
        if is_available is not None:
            query = query.where(AppointmentSlot.is_available == is_available)
        return db.scalars(query.offset(skip).limit(limit)).all()

    @staticmethod
    def create(
        db: Session,
        centre_id: int,
        slot_in: SlotCreate,
        appointment_datetime_utc: datetime,
    ) -> AppointmentSlot:
        """Persist a new appointment slot for a diagnostic centre."""
        slot = AppointmentSlot(
            centre_id=centre_id,
            centre_test_id=slot_in.centre_test_id,
            appointment_datetime=appointment_datetime_utc,
            is_available=slot_in.is_available,
        )
        db.add(slot)
        db.commit()
        db.refresh(slot)
        return slot
