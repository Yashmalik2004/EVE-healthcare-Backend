"""Booking business logic service layer with centralized state machine."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
    ValidationException,
)
from app.core.logging import logger
from app.models.booking import Booking
from app.models.enums import BookingStatus, UserRole
from app.models.user import User
from app.repositories.booking_repository import BookingRepository
from app.repositories.centre_repository import CentreRepository
from app.repositories.slot_repository import SlotRepository
from app.schemas.booking import BookingCreate


class BookingService:
    """Service orchestrating booking creation, lifecycle state transitions, and authorization."""

    def __init__(
        self,
        booking_repo: type[BookingRepository] = BookingRepository,
        centre_repo: type[CentreRepository] = CentreRepository,
        slot_repo: type[SlotRepository] = SlotRepository,
    ):
        self.booking_repo = booking_repo
        self.centre_repo = centre_repo
        self.slot_repo = slot_repo

    @staticmethod
    def generate_booking_reference() -> str:
        """Generate human-readable, unique booking reference string (e.g. BKG-20260930-A1B2C3D4)."""
        date_prefix = datetime.now(UTC).strftime("%Y%m%d")
        unique_suffix = uuid.uuid4().hex[:8].upper()
        return f"BKG-{date_prefix}-{unique_suffix}"

    def create_booking(self, db: Session, user: User, booking_in: BookingCreate) -> Booking:
        """Create a new booking in PENDING state with atomic row-level slot locking.

        Enforces:
        1. CentreTest exists and is currently available.
        2. DiagnosticCentre is active.
        3. DiagnosticTest is active.
        4. AppointmentSlot exists and belongs to the same Centre.
        5. Slot is locked using SELECT ... FOR UPDATE (row-level lock) to prevent race conditions.
        6. Slot is available and scheduled in the future.
        7. Slot is marked unavailable.
        8. CentreTest.price is snapshotted into Booking.amount (immutable against future price changes).
        9. Booking is persisted in PENDING status.
        """
        logger.info(
            f"Initiating booking: user_id={user.id}, centre_test_id={booking_in.centre_test_id}, "
            f"slot_id={booking_in.appointment_slot_id}"
        )

        # 1. Validate CentreTest offering
        centre_test = self.centre_repo.get_centre_test_by_id(db, booking_in.centre_test_id)
        if not centre_test:
            logger.warning(f"CentreTest id={booking_in.centre_test_id} not found")
            raise NotFoundException("CentreTest", booking_in.centre_test_id)

        if not centre_test.is_available:
            raise ValidationException(
                "TEST_UNAVAILABLE", "The requested diagnostic test is currently unavailable."
            )
        if not centre_test.centre.is_active:
            raise ValidationException(
                "CENTRE_INACTIVE", "The diagnostic centre is currently inactive."
            )
        if not centre_test.test.is_active:
            raise ValidationException("TEST_INACTIVE", "The diagnostic test is currently inactive.")

        # 2. Acquire and lock Appointment Slot (concurrency protection)
        slot = self.slot_repo.get_slot_for_update(db, booking_in.appointment_slot_id)
        if not slot:
            logger.warning(f"AppointmentSlot id={booking_in.appointment_slot_id} not found")
            raise NotFoundException("AppointmentSlot", booking_in.appointment_slot_id)

        # 3. Verify slot belongs to the same centre
        if slot.centre_id != centre_test.centre_id:
            raise ValidationException(
                "INVALID_SLOT_CENTRE",
                "The selected appointment slot does not belong to this centre.",
            )

        # 4. Verify slot is currently free
        if not slot.is_available:
            logger.warning(
                f"Concurrent booking conflict: slot {slot.id} already booked"
            )
            raise ConflictException(
                "SLOT_ALREADY_BOOKED",
                "The selected appointment slot is already booked and unavailable.",
            )

        # 5. Verify slot is scheduled in the future
        slot_dt = slot.appointment_datetime
        if slot_dt.tzinfo is None:
            slot_dt = slot_dt.replace(tzinfo=UTC)
        else:
            slot_dt = slot_dt.astimezone(UTC)

        if slot_dt <= datetime.now(UTC):
            raise ValidationException(
                "PAST_APPOINTMENT_DATE",
                "Cannot book an appointment slot in the past.",
            )

        # 6. Atomically reserve slot & snapshot price
        slot.is_available = False
        amount_snapshot = centre_test.price
        booking_ref = self.generate_booking_reference()

        # 7. Create Booking in PENDING state
        booking = self.booking_repo.create(
            db=db,
            user_id=user.id,
            centre_test_id=centre_test.id,
            slot_id=slot.id,
            amount=amount_snapshot,
            booking_reference=booking_ref,
        )

        db.commit()
        db.refresh(booking)
        logger.info(
            f"Booking created successfully: ref={booking.booking_reference}, "
            f"amount={booking.amount}, status={booking.status}"
        )
        return self.get_booking(db, user, booking.id)

    def get_booking(self, db: Session, user: User, booking_id: int) -> Booking:
        """Fetch booking by ID and verify user authorization (owner or admin)."""
        booking = self.booking_repo.get_by_id(db, booking_id)
        if not booking:
            logger.warning(f"Booking id={booking_id} not found")
            raise NotFoundException("Booking", booking_id)

        if user.role != UserRole.ADMIN and booking.user_id != user.id:
            logger.warning(
                f"Unauthorized booking access attempt: user_id={user.id} on booking_id={booking_id}"
            )
            raise ForbiddenException("You are not authorized to access this booking.")

        return booking

    def list_bookings(
        self, db: Session, user: User, skip: int = 0, limit: int = 100
    ) -> Sequence[Booking]:
        """List bookings for the authenticated user, or all bookings for administrators."""
        if user.role == UserRole.ADMIN:
            return self.booking_repo.list_all(db, skip=skip, limit=limit)
        return self.booking_repo.list_by_user(db, user_id=user.id, skip=skip, limit=limit)

    def transition_status(
        self, db: Session, booking: Booking, new_status: BookingStatus
    ) -> Booking:
        """Centralized state machine transition validator for bookings.

        Valid transitions:
        - PENDING   -> CONFIRMED
        - PENDING   -> FAILED
        - PENDING   -> CANCELLED
        - CONFIRMED -> CANCELLED
        - FAILED    -> (terminal)
        - CANCELLED -> (terminal)

        Frees the appointment slot if transitioned to CANCELLED or FAILED.
        Payment and webhook subsystems must invoke this method.
        """
        current_status = booking.status

        valid_transitions = {
            BookingStatus.PENDING: {
                BookingStatus.CONFIRMED,
                BookingStatus.FAILED,
                BookingStatus.CANCELLED,
            },
            BookingStatus.CONFIRMED: {BookingStatus.CANCELLED},
            BookingStatus.FAILED: set(),
            BookingStatus.CANCELLED: set(),
        }

        if new_status == current_status:
            return booking

        if new_status not in valid_transitions.get(current_status, set()):
            logger.warning(
                f"Illegal state transition attempted: {current_status} -> {new_status} "
                f"for booking {booking.booking_reference}"
            )
            raise ConflictException(
                "INVALID_STATE_TRANSITION",
                f"Illegal booking state transition from '{current_status}' to '{new_status}'.",
            )

        # Release the slot if booking failed or cancelled
        if new_status in (BookingStatus.FAILED, BookingStatus.CANCELLED):
            if booking.appointment_slot:
                booking.appointment_slot.is_available = True

        booking.status = new_status
        db.flush()
        logger.info(
            f"Booking ref={booking.booking_reference} transitioned: "
            f"{current_status} -> {new_status}"
        )
        return booking

    def cancel_booking(self, db: Session, user: User, booking_id: int) -> Booking:
        """Cancel an existing booking and free its appointment slot transactionally."""
        booking = self.booking_repo.get_by_id(db, booking_id)
        if not booking:
            logger.warning(f"Booking id={booking_id} not found for cancellation")
            raise NotFoundException("Booking", booking_id)

        if user.role != UserRole.ADMIN and booking.user_id != user.id:
            logger.warning(
                f"Unauthorized cancellation attempt: user_id={user.id} on booking_id={booking_id}"
            )
            raise ForbiddenException("You are not authorized to cancel this booking.")

        # Disallow cancellation of FAILED bookings explicitly
        if booking.status == BookingStatus.FAILED:
            raise ConflictException(
                "INVALID_STATE_TRANSITION",
                "Cannot cancel a booking that is already in FAILED status.",
            )

        self.transition_status(db, booking, BookingStatus.CANCELLED)
        db.commit()
        db.refresh(booking)
        logger.info(f"Booking ref={booking.booking_reference} cancelled successfully")
        return booking


booking_service = BookingService()
