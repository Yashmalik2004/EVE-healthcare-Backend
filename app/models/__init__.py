"""ORM models package.

All model modules are imported here so that Alembic's ``env.py`` discovers
every table via a single ``import app.models`` statement.

Import order respects FK dependency chains:
    1. Enums        (no dependencies)
    2. User         (no FK dependencies)
    3. DiagnosticCentre / DiagnosticTest  (no FK dependencies)
    4. CentreTest   (depends on Centre + Test)
    5. AppointmentSlot (depends on Centre + CentreTest)
    6. Booking      (depends on User + CentreTest + AppointmentSlot)
    7. Payment      (depends on Booking)
    8. PaymentWebhookEvent (depends on Payment)
"""

from app.models.enums import BookingStatus, PaymentStatus, UserRole
from app.models.user import User
from app.models.centre import DiagnosticCentre
from app.models.diagnostic_test import DiagnosticTest
from app.models.centre_test import CentreTest
from app.models.appointment_slot import AppointmentSlot
from app.models.booking import Booking
from app.models.payment import Payment
from app.models.webhook_event import PaymentWebhookEvent

__all__ = [
    "UserRole",
    "BookingStatus",
    "PaymentStatus",
    "User",
    "DiagnosticCentre",
    "DiagnosticTest",
    "CentreTest",
    "AppointmentSlot",
    "Booking",
    "Payment",
    "PaymentWebhookEvent",
]
