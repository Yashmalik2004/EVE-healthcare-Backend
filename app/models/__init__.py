"""ORM models package.

Import every model module here so that Alembic's ``env.py`` discovers all
tables via a single ``import app.models`` statement.

Models will be added in subsequent phases:
- Phase 2: User
- Phase 3: DiagnosticCentre, DiagnosticTest, AppointmentSlot, CentreTest
- Phase 4: Booking
- Phase 5: Payment, WebhookEvent
"""

# No models yet — placeholder so Alembic import succeeds.
