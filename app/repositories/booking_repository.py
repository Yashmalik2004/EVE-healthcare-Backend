"""Booking data access layer."""

from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.booking import Booking
from app.models.centre_test import CentreTest
from app.models.enums import BookingStatus


class BookingRepository:
    """Repository handling database queries and persistence for bookings."""

    @staticmethod
    def get_by_id(db: Session, booking_id: int) -> Booking | None:
        """Fetch booking by primary key with all associated relations loaded."""
        return db.scalar(
            select(Booking)
            .where(Booking.id == booking_id)
            .options(
                selectinload(Booking.user),
                selectinload(Booking.centre_test).selectinload(CentreTest.test),
                selectinload(Booking.centre_test).selectinload(CentreTest.centre),
                selectinload(Booking.appointment_slot),
            )
        )

    @staticmethod
    def get_by_reference(db: Session, booking_reference: str) -> Booking | None:
        """Fetch booking by external booking reference string."""
        return db.scalar(
            select(Booking)
            .where(Booking.booking_reference == booking_reference)
            .options(
                selectinload(Booking.user),
                selectinload(Booking.centre_test).selectinload(CentreTest.test),
                selectinload(Booking.centre_test).selectinload(CentreTest.centre),
                selectinload(Booking.appointment_slot),
            )
        )

    @staticmethod
    def list_by_user(
        db: Session, user_id: int, skip: int = 0, limit: int = 100
    ) -> Sequence[Booking]:
        """List bookings created by a specific user ordered by newest first."""
        return db.scalars(
            select(Booking)
            .where(Booking.user_id == user_id)
            .order_by(Booking.created_at.desc())
            .offset(skip)
            .limit(limit)
            .options(
                selectinload(Booking.centre_test).selectinload(CentreTest.test),
                selectinload(Booking.appointment_slot),
            )
        ).all()

    @staticmethod
    def list_all(db: Session, skip: int = 0, limit: int = 100) -> Sequence[Booking]:
        """List all bookings across the platform for administrative queries."""
        return db.scalars(
            select(Booking)
            .order_by(Booking.created_at.desc())
            .offset(skip)
            .limit(limit)
            .options(
                selectinload(Booking.user),
                selectinload(Booking.centre_test).selectinload(CentreTest.test),
                selectinload(Booking.appointment_slot),
            )
        ).all()

    @staticmethod
    def create(
        db: Session,
        *,
        user_id: int,
        centre_test_id: int,
        slot_id: int,
        amount: Decimal,
        booking_reference: str,
    ) -> Booking:
        """Create and flush a new Booking row in PENDING status."""
        booking = Booking(
            user_id=user_id,
            centre_test_id=centre_test_id,
            appointment_slot_id=slot_id,
            amount=amount,
            booking_reference=booking_reference,
            status=BookingStatus.PENDING,
        )
        db.add(booking)
        db.flush()
        db.refresh(booking)
        return booking

    @staticmethod
    def update_status(db: Session, booking: Booking, new_status: BookingStatus) -> Booking:
        """Update booking status and flush changes."""
        booking.status = new_status
        db.flush()
        db.refresh(booking)
        return booking
