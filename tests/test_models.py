"""Model smoke tests — Phase 2.

Verifies that:
1. All tables are created correctly by Base.metadata.create_all().
2. All ORM models can be instantiated and persisted.
3. Relationships traverse correctly.
4. Unique constraints are enforced.
5. Numeric(10,2) columns preserve decimal precision (no float corruption).

These tests run entirely against the in-memory SQLite database configured
in conftest.py — no PostgreSQL required.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.models import (
    AppointmentSlot,
    Booking,
    BookingStatus,
    CentreTest,
    DiagnosticCentre,
    DiagnosticTest,
    Payment,
    PaymentStatus,
    PaymentWebhookEvent,
    User,
    UserRole,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def make_user(email: str = "patient@example.com") -> User:
    return User(
        email=email,
        password_hash="hashed_pw",
        full_name="Test Patient",
        role=UserRole.PATIENT,
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def make_centre(name: str = "City Lab") -> DiagnosticCentre:
    return DiagnosticCentre(
        name=name,
        address="123 Main St",
        city="Mumbai",
        state="Maharashtra",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def make_test(name: str = "CBC") -> DiagnosticTest:
    return DiagnosticTest(
        name=name,
        description="Complete Blood Count",
        category="Haematology",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


# ── Table Creation ────────────────────────────────────────────────────────────


def test_all_tables_exist(db):
    """Verify all 8 domain tables are created in the test database."""
    inspector = inspect(db.bind)
    tables = set(inspector.get_table_names())
    expected = {
        "users",
        "diagnostic_centres",
        "diagnostic_tests",
        "centre_tests",
        "appointment_slots",
        "bookings",
        "payments",
        "payment_webhook_events",
    }
    assert expected.issubset(tables), f"Missing tables: {expected - tables}"


# ── Model Instantiation ───────────────────────────────────────────────────────


def test_user_create_and_retrieve(db):
    """Create a User and retrieve it by PK."""
    user = make_user()
    db.add(user)
    db.flush()

    fetched = db.get(User, user.id)
    assert fetched is not None
    assert fetched.email == "patient@example.com"
    assert fetched.role == UserRole.PATIENT
    assert fetched.is_active is True


def test_centre_create(db):
    """Create a DiagnosticCentre and persist."""
    centre = make_centre()
    db.add(centre)
    db.flush()
    assert centre.id is not None
    assert centre.city == "Mumbai"


def test_diagnostic_test_create(db):
    """Create a DiagnosticTest and persist."""
    test = make_test()
    db.add(test)
    db.flush()
    assert test.id is not None
    assert test.category == "Haematology"


def test_centre_test_create(db):
    """Create CentreTest and verify Numeric price stored correctly."""
    centre = make_centre()
    test = make_test()
    db.add_all([centre, test])
    db.flush()

    ct = CentreTest(
        centre_id=centre.id,
        test_id=test.id,
        price=Decimal("750.50"),
        is_available=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(ct)
    db.flush()

    fetched = db.get(CentreTest, ct.id)
    assert fetched.price == Decimal("750.50")


def test_appointment_slot_create(db):
    """Create an AppointmentSlot."""
    centre = make_centre()
    db.add(centre)
    db.flush()

    slot = AppointmentSlot(
        centre_id=centre.id,
        appointment_datetime=datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
        is_available=True,
        created_at=datetime.now(UTC),
    )
    db.add(slot)
    db.flush()
    assert slot.id is not None
    assert slot.is_available is True


def test_full_booking_chain(db):
    """Create User → Centre → Test → CentreTest → Slot → Booking."""
    user = make_user(email="chain@example.com")
    centre = make_centre(name="Chain Lab")
    test = make_test(name="Lipid Panel")
    db.add_all([user, centre, test])
    db.flush()

    ct = CentreTest(
        centre_id=centre.id,
        test_id=test.id,
        price=Decimal("1200.00"),
        is_available=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(ct)
    db.flush()

    slot = AppointmentSlot(
        centre_id=centre.id,
        centre_test_id=ct.id,
        appointment_datetime=datetime(2026, 10, 2, 10, 0, tzinfo=UTC),
        is_available=True,
        created_at=datetime.now(UTC),
    )
    db.add(slot)
    db.flush()

    booking = Booking(
        booking_reference="EVE-TEST-001",
        user_id=user.id,
        centre_test_id=ct.id,
        appointment_slot_id=slot.id,
        amount=Decimal("1200.00"),
        status=BookingStatus.PENDING,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(booking)
    db.flush()

    assert booking.id is not None
    assert booking.status == BookingStatus.PENDING
    # Relationship traversal
    assert booking.centre_test.price == Decimal("1200.00")
    assert booking.user.email == "chain@example.com"


def test_payment_create(db):
    """Create a Payment linked to a Booking."""
    user = make_user(email="pay@example.com")
    centre = make_centre(name="Pay Lab")
    test = make_test(name="Thyroid")
    db.add_all([user, centre, test])
    db.flush()

    ct = CentreTest(
        centre_id=centre.id,
        test_id=test.id,
        price=Decimal("500.00"),
        is_available=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(ct)
    db.flush()

    slot = AppointmentSlot(
        centre_id=centre.id,
        appointment_datetime=datetime(2026, 10, 3, 11, 0, tzinfo=UTC),
        is_available=True,
        created_at=datetime.now(UTC),
    )
    db.add(slot)
    db.flush()

    booking = Booking(
        booking_reference="EVE-PAY-001",
        user_id=user.id,
        centre_test_id=ct.id,
        appointment_slot_id=slot.id,
        amount=Decimal("500.00"),
        status=BookingStatus.PENDING,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(booking)
    db.flush()

    payment = Payment(
        payment_reference="PAY-001",
        booking_id=booking.id,
        amount=Decimal("500.00"),
        status=PaymentStatus.PENDING,
        provider="mock_gateway",
        idempotency_key="idem-001",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(payment)
    db.flush()

    assert payment.id is not None
    assert payment.amount == Decimal("500.00")
    assert payment.booking.booking_reference == "EVE-PAY-001"


def test_webhook_event_create(db):
    """Create a PaymentWebhookEvent standalone (no FK to payment)."""
    event = PaymentWebhookEvent(
        event_id="evt_webhook_001",
        event_type="payment.success",
        payment_reference="PAY-001",
        payload='{"status": "SUCCESS"}',
        created_at=datetime.now(UTC),
    )
    db.add(event)
    db.flush()
    assert event.id is not None
    assert event.processed_at is None


# ── Unique Constraint Tests ───────────────────────────────────────────────────


def test_user_email_unique(db):
    """Duplicate email raises IntegrityError."""
    db.add(make_user(email="dup@example.com"))
    db.flush()

    with pytest.raises(IntegrityError):
        db.add(make_user(email="dup@example.com"))
        db.flush()


def test_centre_test_unique_constraint(db):
    """Duplicate (centre_id, test_id) raises IntegrityError."""
    centre = make_centre(name="Unique Lab")
    test = make_test(name="Unique Test")
    db.add_all([centre, test])
    db.flush()

    ct1 = CentreTest(
        centre_id=centre.id,
        test_id=test.id,
        price=Decimal("100.00"),
        is_available=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(ct1)
    db.flush()

    with pytest.raises(IntegrityError):
        ct2 = CentreTest(
            centre_id=centre.id,
            test_id=test.id,
            price=Decimal("200.00"),
            is_available=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db.add(ct2)
        db.flush()


def test_booking_reference_unique(db):
    """Duplicate booking_reference raises IntegrityError."""
    user = make_user(email="bref@example.com")
    centre = make_centre(name="BRef Lab")
    test = make_test(name="BRef Test")
    db.add_all([user, centre, test])
    db.flush()

    ct = CentreTest(
        centre_id=centre.id,
        test_id=test.id,
        price=Decimal("100.00"),
        is_available=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(ct)
    db.flush()

    slot1 = AppointmentSlot(
        centre_id=centre.id,
        appointment_datetime=datetime(2026, 10, 4, 9, 0, tzinfo=UTC),
        is_available=True,
        created_at=datetime.now(UTC),
    )
    slot2 = AppointmentSlot(
        centre_id=centre.id,
        appointment_datetime=datetime(2026, 10, 4, 10, 0, tzinfo=UTC),
        is_available=True,
        created_at=datetime.now(UTC),
    )
    db.add_all([slot1, slot2])
    db.flush()

    b1 = Booking(
        booking_reference="EVE-DUP-001",
        user_id=user.id,
        centre_test_id=ct.id,
        appointment_slot_id=slot1.id,
        amount=Decimal("100.00"),
        status=BookingStatus.PENDING,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(b1)
    db.flush()

    with pytest.raises(IntegrityError):
        b2 = Booking(
            booking_reference="EVE-DUP-001",  # duplicate!
            user_id=user.id,
            centre_test_id=ct.id,
            appointment_slot_id=slot2.id,
            amount=Decimal("100.00"),
            status=BookingStatus.PENDING,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db.add(b2)
        db.flush()


def test_webhook_event_id_unique(db):
    """Duplicate event_id raises IntegrityError."""
    e1 = PaymentWebhookEvent(
        event_id="evt_dup",
        event_type="payment.success",
        payment_reference="PAY-X",
        payload="{}",
        created_at=datetime.now(UTC),
    )
    db.add(e1)
    db.flush()

    with pytest.raises(IntegrityError):
        e2 = PaymentWebhookEvent(
            event_id="evt_dup",  # duplicate!
            event_type="payment.failed",
            payment_reference="PAY-Y",
            payload="{}",
            created_at=datetime.now(UTC),
        )
        db.add(e2)
        db.flush()


def test_payment_idempotency_key_unique(db):
    """Duplicate idempotency_key raises IntegrityError."""
    user = make_user(email="idem@example.com")
    centre = make_centre(name="Idem Lab")
    test = make_test(name="Idem Test")
    db.add_all([user, centre, test])
    db.flush()

    ct = CentreTest(
        centre_id=centre.id,
        test_id=test.id,
        price=Decimal("100.00"),
        is_available=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(ct)
    db.flush()

    slot = AppointmentSlot(
        centre_id=centre.id,
        appointment_datetime=datetime(2026, 10, 5, 9, 0, tzinfo=UTC),
        is_available=True,
        created_at=datetime.now(UTC),
    )
    db.add(slot)
    db.flush()

    booking = Booking(
        booking_reference="EVE-IDEM-001",
        user_id=user.id,
        centre_test_id=ct.id,
        appointment_slot_id=slot.id,
        amount=Decimal("100.00"),
        status=BookingStatus.PENDING,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(booking)
    db.flush()

    p1 = Payment(
        payment_reference="PAY-IDEM-001",
        booking_id=booking.id,
        amount=Decimal("100.00"),
        status=PaymentStatus.PENDING,
        provider="mock_gateway",
        idempotency_key="unique-idem-key",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(p1)
    db.flush()

    with pytest.raises(IntegrityError):
        p2 = Payment(
            payment_reference="PAY-IDEM-002",
            booking_id=booking.id,
            amount=Decimal("100.00"),
            status=PaymentStatus.PENDING,
            provider="mock_gateway",
            idempotency_key="unique-idem-key",  # duplicate!
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db.add(p2)
        db.flush()


# ── Precision Test ────────────────────────────────────────────────────────────


def test_numeric_price_precision(db):
    """Numeric(10,2) must not suffer float rounding errors."""
    centre = make_centre(name="Precision Lab")
    test = make_test(name="Precision Test")
    db.add_all([centre, test])
    db.flush()

    price = Decimal("999.99")
    ct = CentreTest(
        centre_id=centre.id,
        test_id=test.id,
        price=price,
        is_available=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(ct)
    db.flush()
    db.refresh(ct)
    assert ct.price == price, f"Precision lost: expected {price}, got {ct.price}"


# ── Migration Smoke Test ──────────────────────────────────────────────────────


def test_migration_sql_syntax():
    """Load the migration file directly to verify it has no syntax errors."""
    import importlib.util
    import pathlib

    migration_path = (
        pathlib.Path(__file__).parent.parent
        / "alembic"
        / "versions"
        / "001_initial_schema.py"
    )
    spec = importlib.util.spec_from_file_location("migration_001", migration_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert callable(module.upgrade)
    assert callable(module.downgrade)
