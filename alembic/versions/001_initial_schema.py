"""initial_schema

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-09-30

Complete initial database schema for the EVE Healthcare Backend.

Tables created (in FK dependency order):
    1. users
    2. diagnostic_centres
    3. diagnostic_tests
    4. payment_webhook_events  (no FKs in base columns)
    5. centre_tests            (FK → centres, tests)
    6. appointment_slots       (FK → centres, centre_tests)
    7. bookings                (FK → users, centre_tests, appointment_slots)
    8. payments                (FK → bookings)
    9. payment_webhook_events  (FK → payments via payment_id)

Note: payment_webhook_events is created before payments for the event_id
unique index, but the FK to payments.id is added as part of the table def.
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic
revision: str = "001_initial_schema"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the full initial schema."""

    # ── users ──────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column(
            "role",
            sa.Enum("PATIENT", "ADMIN", name="user_role", native_enum=False),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_id"), "users", ["id"], unique=False)
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    # ── diagnostic_centres ────────────────────────────────────────────────
    op.create_table(
        "diagnostic_centres",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("address", sa.String(length=500), nullable=False),
        sa.Column("city", sa.String(length=100), nullable=False),
        sa.Column("state", sa.String(length=100), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_diagnostic_centres_id"), "diagnostic_centres", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_diagnostic_centres_name"), "diagnostic_centres", ["name"], unique=False
    )
    op.create_index(
        op.f("ix_diagnostic_centres_city"), "diagnostic_centres", ["city"], unique=False
    )

    # ── diagnostic_tests ─────────────────────────────────────────────────
    op.create_table(
        "diagnostic_tests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_diagnostic_tests_id"), "diagnostic_tests", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_diagnostic_tests_name"), "diagnostic_tests", ["name"], unique=False
    )
    op.create_index(
        op.f("ix_diagnostic_tests_category"), "diagnostic_tests", ["category"], unique=False
    )

    # ── centre_tests ──────────────────────────────────────────────────────
    op.create_table(
        "centre_tests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("centre_id", sa.Integer(), nullable=False),
        sa.Column("test_id", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("is_available", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["centre_id"], ["diagnostic_centres.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["test_id"], ["diagnostic_tests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("centre_id", "test_id", name="uq_centre_test"),
    )
    op.create_index(op.f("ix_centre_tests_id"), "centre_tests", ["id"], unique=False)
    op.create_index(
        op.f("ix_centre_tests_centre_id"), "centre_tests", ["centre_id"], unique=False
    )
    op.create_index(
        op.f("ix_centre_tests_test_id"), "centre_tests", ["test_id"], unique=False
    )

    # ── appointment_slots ─────────────────────────────────────────────────
    op.create_table(
        "appointment_slots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("centre_id", sa.Integer(), nullable=False),
        sa.Column("centre_test_id", sa.Integer(), nullable=True),
        sa.Column("appointment_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_available", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["centre_id"], ["diagnostic_centres.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["centre_test_id"], ["centre_tests.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_appointment_slots_id"), "appointment_slots", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_appointment_slots_centre_id"),
        "appointment_slots",
        ["centre_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_appointment_slots_centre_test_id"),
        "appointment_slots",
        ["centre_test_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_appointment_slots_appointment_datetime"),
        "appointment_slots",
        ["appointment_datetime"],
        unique=False,
    )
    op.create_index(
        op.f("ix_appointment_slots_is_available"),
        "appointment_slots",
        ["is_available"],
        unique=False,
    )

    # ── bookings ──────────────────────────────────────────────────────────
    op.create_table(
        "bookings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("booking_reference", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("centre_test_id", sa.Integer(), nullable=False),
        sa.Column("appointment_slot_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "CONFIRMED",
                "FAILED",
                "CANCELLED",
                name="booking_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["centre_test_id"], ["centre_tests.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["appointment_slot_id"], ["appointment_slots.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_bookings_id"), "bookings", ["id"], unique=False)
    op.create_index(
        op.f("ix_bookings_booking_reference"),
        "bookings",
        ["booking_reference"],
        unique=True,
    )
    op.create_index(op.f("ix_bookings_user_id"), "bookings", ["user_id"], unique=False)
    op.create_index(
        op.f("ix_bookings_centre_test_id"), "bookings", ["centre_test_id"], unique=False
    )
    op.create_index(
        op.f("ix_bookings_appointment_slot_id"),
        "bookings",
        ["appointment_slot_id"],
        unique=False,
    )
    op.create_index(op.f("ix_bookings_status"), "bookings", ["status"], unique=False)

    # ── payments ──────────────────────────────────────────────────────────
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("payment_reference", sa.String(length=64), nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column(
            "status",
            sa.Enum("PENDING", "SUCCESS", "FAILED", name="payment_status", native_enum=False),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("provider_transaction_id", sa.String(length=100), nullable=True),
        sa.Column("idempotency_key", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_payments_id"), "payments", ["id"], unique=False)
    op.create_index(
        op.f("ix_payments_payment_reference"),
        "payments",
        ["payment_reference"],
        unique=True,
    )
    op.create_index(
        op.f("ix_payments_booking_id"), "payments", ["booking_id"], unique=False
    )
    op.create_index(op.f("ix_payments_status"), "payments", ["status"], unique=False)
    op.create_index(
        op.f("ix_payments_idempotency_key"),
        "payments",
        ["idempotency_key"],
        unique=True,
    )

    # ── payment_webhook_events ────────────────────────────────────────────
    op.create_table(
        "payment_webhook_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(length=100), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payment_reference", sa.String(length=100), nullable=False),
        sa.Column("payment_id", sa.Integer(), nullable=True),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_payment_webhook_events_id"),
        "payment_webhook_events",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_payment_webhook_events_event_id"),
        "payment_webhook_events",
        ["event_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_payment_webhook_events_event_type"),
        "payment_webhook_events",
        ["event_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_payment_webhook_events_payment_reference"),
        "payment_webhook_events",
        ["payment_reference"],
        unique=False,
    )
    op.create_index(
        op.f("ix_payment_webhook_events_payment_id"),
        "payment_webhook_events",
        ["payment_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop all tables in reverse dependency order."""
    # Dependent tables first
    op.drop_index(op.f("ix_payment_webhook_events_payment_id"), table_name="payment_webhook_events")
    op.drop_index(op.f("ix_payment_webhook_events_payment_reference"), table_name="payment_webhook_events")
    op.drop_index(op.f("ix_payment_webhook_events_event_type"), table_name="payment_webhook_events")
    op.drop_index(op.f("ix_payment_webhook_events_event_id"), table_name="payment_webhook_events")
    op.drop_index(op.f("ix_payment_webhook_events_id"), table_name="payment_webhook_events")
    op.drop_table("payment_webhook_events")

    op.drop_index(op.f("ix_payments_idempotency_key"), table_name="payments")
    op.drop_index(op.f("ix_payments_status"), table_name="payments")
    op.drop_index(op.f("ix_payments_booking_id"), table_name="payments")
    op.drop_index(op.f("ix_payments_payment_reference"), table_name="payments")
    op.drop_index(op.f("ix_payments_id"), table_name="payments")
    op.drop_table("payments")

    op.drop_index(op.f("ix_bookings_status"), table_name="bookings")
    op.drop_index(op.f("ix_bookings_appointment_slot_id"), table_name="bookings")
    op.drop_index(op.f("ix_bookings_centre_test_id"), table_name="bookings")
    op.drop_index(op.f("ix_bookings_user_id"), table_name="bookings")
    op.drop_index(op.f("ix_bookings_booking_reference"), table_name="bookings")
    op.drop_index(op.f("ix_bookings_id"), table_name="bookings")
    op.drop_table("bookings")

    op.drop_index(op.f("ix_appointment_slots_is_available"), table_name="appointment_slots")
    op.drop_index(op.f("ix_appointment_slots_appointment_datetime"), table_name="appointment_slots")
    op.drop_index(op.f("ix_appointment_slots_centre_test_id"), table_name="appointment_slots")
    op.drop_index(op.f("ix_appointment_slots_centre_id"), table_name="appointment_slots")
    op.drop_index(op.f("ix_appointment_slots_id"), table_name="appointment_slots")
    op.drop_table("appointment_slots")

    op.drop_index(op.f("ix_centre_tests_test_id"), table_name="centre_tests")
    op.drop_index(op.f("ix_centre_tests_centre_id"), table_name="centre_tests")
    op.drop_index(op.f("ix_centre_tests_id"), table_name="centre_tests")
    op.drop_table("centre_tests")

    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_index(op.f("ix_users_id"), table_name="users")
    op.drop_table("users")

    op.drop_index(op.f("ix_diagnostic_tests_category"), table_name="diagnostic_tests")
    op.drop_index(op.f("ix_diagnostic_tests_name"), table_name="diagnostic_tests")
    op.drop_index(op.f("ix_diagnostic_tests_id"), table_name="diagnostic_tests")
    op.drop_table("diagnostic_tests")

    op.drop_index(op.f("ix_diagnostic_centres_city"), table_name="diagnostic_centres")
    op.drop_index(op.f("ix_diagnostic_centres_name"), table_name="diagnostic_centres")
    op.drop_index(op.f("ix_diagnostic_centres_id"), table_name="diagnostic_centres")
    op.drop_table("diagnostic_centres")
