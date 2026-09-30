# EVE Healthcare Diagnostic Booking Backend

A production-grade REST API for diagnostic test booking, simulated payment processing, and webhook event handling. Built as part of the EVE Healthcare SDE Intern Assessment.

---

## Overview

The service manages the complete lifecycle of a diagnostic test booking:

1. A user **registers and authenticates** via JWT.
2. They **browse** diagnostic centres and the tests those centres offer.
3. They **create a booking** — the system locks the appointment slot atomically and snapshots the price.
4. They **submit a payment** — the system validates the amount and transitions the booking state.
5. The **payment gateway** calls back via webhook — the system processes it idempotently and finalises the booking.

---

## Features

- JWT authentication with Argon2 password hashing
- Role-based access control (PATIENT / ADMIN)
- Diagnostic centre and test catalogue management
- Appointment slot management with future-date validation
- Atomic slot reservation with row-level locking (SELECT … FOR UPDATE)
- Price snapshotting at booking time
- Centralised booking state machine with transition validation
- Simulated payment processing (SUCCESS / FAILED)
- Client-side idempotency key support for payments
- Payment webhook processing with two-layer idempotency (application + database)
- Consistent JSON error envelope across all endpoints
- Structured request logging with sensitive-data redaction
- Docker Compose deployment with automatic Alembic migrations

---

## Architecture

```
HTTP Request
     │
     ▼
┌─────────────┐
│  FastAPI    │  Route handlers — thin wiring only
│  Router     │
└──────┬──────┘
       │ calls
       ▼
┌─────────────┐
│  Service    │  Business logic, state machine, validation
│  Layer      │
└──────┬──────┘
       │ calls
       ▼
┌─────────────┐
│ Repository  │  Data access — all raw ORM queries here
│  Layer      │
└──────┬──────┘
       │ uses
       ▼
┌─────────────┐
│  SQLAlchemy │  ORM models + Alembic migrations
│  + Postgres │
└─────────────┘
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | FastAPI 0.115+ |
| ORM | SQLAlchemy 2.0 (mapped_column style) |
| Migrations | Alembic |
| Database | PostgreSQL (prod) / SQLite (tests) |
| Validation | Pydantic v2 + pydantic-settings |
| Auth | PyJWT (HS256) + argon2-cffi |
| Testing | pytest + httpx (152 tests) |
| Container | Docker + Docker Compose |
| Python | 3.12 |

---

## Project Structure

```
eve-healthcare-backend/
├── app/
│   ├── api/
│   │   ├── deps.py           # get_current_active_user dependency
│   │   └── routes/
│   │       ├── auth.py       # POST /auth/signup, POST /auth/login, GET /auth/me
│   │       ├── centres.py    # CRUD + tests + slots sub-routes
│   │       ├── tests.py      # Global diagnostic test catalogue
│   │       ├── bookings.py   # Booking lifecycle
│   │       ├── payments.py   # Simulated payment processing
│   │       ├── webhook.py    # Payment gateway callback
│   │       └── health.py     # Liveness + DB readiness probe
│   ├── core/
│   │   ├── config.py         # pydantic-settings (env vars)
│   │   ├── exceptions.py     # AppException hierarchy
│   │   ├── logging.py        # Structured logger + sensitive-data filter
│   │   └── security.py       # JWT encode/decode + Argon2 hashing
│   ├── db/
│   │   └── database.py       # Engine, session factory, Base, get_db
│   ├── models/
│   │   ├── enums.py          # UserRole, BookingStatus, PaymentStatus
│   │   ├── user.py
│   │   ├── centre.py
│   │   ├── diagnostic_test.py
│   │   ├── centre_test.py    # Centre × Test association with price
│   │   ├── appointment_slot.py
│   │   ├── booking.py        # Price snapshot, state, relationships
│   │   ├── payment.py        # Idempotency key, provider fields
│   │   └── webhook_event.py  # event_id unique constraint
│   ├── repositories/         # Data access layer (one class per model)
│   ├── schemas/              # Pydantic request/response models
│   ├── services/             # Business logic (one class per domain)
│   └── main.py               # App factory, middleware, exception handlers
├── alembic/
│   └── versions/
│       └── 001_initial_schema.py  # Full schema in one migration
├── tests/                    # 152 pytest tests
├── Dockerfile                # Multi-stage production image
├── docker-compose.yml        # api + db services
├── .env.example
├── alembic.ini
└── pyproject.toml
```

---

## Database Design

```
users
  id PK | email UNIQUE | password_hash | full_name | role | is_active | timestamps

diagnostic_centres
  id PK | name | address | city | state | latitude | longitude | is_active | timestamps

diagnostic_tests
  id PK | name | description | category | is_active | timestamps

centre_tests                              ← Centre × Test association
  id PK | centre_id FK | test_id FK | price NUMERIC(10,2) | is_available | timestamps
  UNIQUE(centre_id, test_id)

appointment_slots
  id PK | centre_id FK | centre_test_id FK (nullable) | appointment_datetime | is_available | created_at

bookings
  id PK | booking_reference UNIQUE | user_id FK | centre_test_id FK
        | appointment_slot_id FK | amount NUMERIC(10,2) | status | timestamps

payments
  id PK | payment_reference UNIQUE | booking_id FK | amount NUMERIC(10,2)
        | status | provider | provider_transaction_id | idempotency_key UNIQUE | timestamps

payment_webhook_events
  id PK | event_id UNIQUE | event_type | payment_reference | payment_id FK (SET NULL)
        | payload TEXT | processed_at | created_at
```

**Design notes:**
- All monetary values use `NUMERIC(10,2)` — never `FLOAT`.
- `booking.amount` is a price snapshot; it does not update when `centre_test.price` changes.
- `payment_webhook_events.event_id` has a database-level `UNIQUE` constraint for idempotency safety.
- Foreign keys use `ondelete="RESTRICT"` on booking/payment links to prevent accidental deletion of financial records.

---

## Booking State Machine

```
              [POST /bookings]
                    │
                    ▼
              ┌─────────┐
              │ PENDING │
              └────┬────┘
          ┌────────┴────────┐
          │                 │
   payment SUCCESS    payment FAILED
          │                 │
          ▼                 ▼
    ┌───────────┐      ┌────────┐
    │ CONFIRMED │      │ FAILED │  (terminal)
    └─────┬─────┘      └────────┘
          │
   user cancels (or
   webhook: FAILED)
          │
          ▼
    ┌───────────┐
    │ CANCELLED │  (terminal)
    └───────────┘
```

**Rules enforced in `BookingService.transition_status`:**
- FAILED and CANCELLED are terminal — no further transitions.
- Invalid transitions raise HTTP 409 with code `INVALID_STATE_TRANSITION`.
- Slot is freed (`is_available = True`) on CANCELLED or FAILED.

---

## Payment Flow

```
Client                       API                          DB
  │                           │                            │
  │ POST /payments             │                            │
  │ {booking_id, amount,       │                            │
  │  simulate_status}          │                            │
  │ Idempotency-Key: <key>  ──►│                            │
  │                           │── 1. Check idempotency key─►│
  │                           │◄─ existing? return it       │
  │                           │── 2. Fetch booking          │
  │                           │── 3. Ownership check        │
  │                           │── 4. Status guards          │
  │                           │── 5. Duplicate success guard│
  │                           │── 6. Amount == booking.amount│
  │                           │── 7. INSERT payment         │
  │                           │── 8. Transition booking     │
  │                           │── 9. COMMIT (atomic)        │
  │◄──── 201 PaymentResponse  │                            │
```

**Amount manipulation is prevented:** step 6 compares the client-supplied `amount` against the authoritative `booking.amount` (price snapshot) and rejects any mismatch with HTTP 422 / `PAYMENT_AMOUNT_MISMATCH`.

---

## Webhook Idempotency

```
POST /payments/webhook
{event_id, event_type, payment_id, status}

Layer 1 — Application fast path:
  SELECT * FROM payment_webhook_events WHERE event_id = ?
  → found: return ALREADY_PROCESSED immediately (no writes)

Layer 2 — Database UNIQUE constraint:
  If two identical events race past Layer 1:
    Only ONE INSERT succeeds (event_id UNIQUE)
    Loser catches IntegrityError → rollback → re-query → ALREADY_PROCESSED

All within one transaction:
  payment.status update  +  booking state transition  +  webhook event INSERT
  committed atomically with a single db.commit()
```

---

## Authentication & Authorization

| Mechanism | Detail |
|---|---|
| Password hashing | Argon2id via `argon2-cffi` |
| Token format | JWT HS256, signed with `SECRET_KEY` |
| Token payload | `sub` (user ID), `email`, `role` |
| Token expiry | Configurable via `ACCESS_TOKEN_EXPIRE_MINUTES` (default 60 min) |
| Role escalation | `POST /auth/signup` always assigns `PATIENT` role — no client input accepted |
| Resource ownership | Bookings and payments are scoped to the authenticated user; ADMINs can access all |

---

## API Endpoints

### Health

| Method | Path | Auth | Status |
|---|---|---|---|
| GET | `/` | — | 200 |
| GET | `/health` | — | 200 / 503 |

### Authentication — `/api/v1/auth`

| Method | Path | Auth | Status |
|---|---|---|---|
| POST | `/auth/signup` | — | 201 |
| POST | `/auth/login` | — | 200 |
| GET | `/auth/me` | ✅ Bearer | 200 |

### Diagnostic Centres — `/api/v1/centres`

| Method | Path | Auth | Status |
|---|---|---|---|
| GET | `/centres` | — | 200 |
| POST | `/centres` | ✅ Bearer | 201 |
| GET | `/centres/{id}` | — | 200 |
| PATCH | `/centres/{id}` | ✅ Bearer | 200 |
| GET | `/centres/{id}/tests` | — | 200 |
| POST | `/centres/{id}/tests` | ✅ Bearer | 201 |
| GET | `/centres/{id}/slots` | — | 200 |
| POST | `/centres/{id}/slots` | ✅ Bearer | 201 |

### Diagnostic Tests — `/api/v1/tests`

| Method | Path | Auth | Status |
|---|---|---|---|
| GET | `/tests` | — | 200 |
| POST | `/tests` | ✅ Bearer | 201 |
| GET | `/tests/{id}` | — | 200 |

### Bookings — `/api/v1/bookings`

| Method | Path | Auth | Status |
|---|---|---|---|
| POST | `/bookings` | ✅ Bearer | 201 |
| GET | `/bookings` | ✅ Bearer | 200 |
| GET | `/bookings/{id}` | ✅ Bearer | 200 |
| POST | `/bookings/{id}/cancel` | ✅ Bearer | 200 |

### Payments — `/api/v1/payments`

| Method | Path | Auth | Status |
|---|---|---|---|
| POST | `/payments` | ✅ Bearer | 201 |
| GET | `/payments/{id}` | ✅ Bearer | 200 |
| POST | `/payments/webhook` | — (no auth) | 200 |

---

## Example Requests

### Register

```bash
curl -X POST http://localhost:8000/api/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email": "patient@example.com", "password": "SecurePass123!", "full_name": "Jane Doe"}'
```

### Login

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "patient@example.com", "password": "SecurePass123!"}'
# Response: {"access_token": "...", "token_type": "bearer", "user": {...}}
```

### Create a Booking

```bash
curl -X POST http://localhost:8000/api/v1/bookings \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"centre_test_id": 1, "appointment_slot_id": 1}'
# Response: {"id": 1, "booking_reference": "BKG-20260930-A1B2C3D4", "status": "PENDING", "amount": "500.00", ...}
```

### Pay for a Booking (with idempotency key)

```bash
curl -X POST http://localhost:8000/api/v1/payments \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: my-unique-key-001" \
  -d '{"booking_id": 1, "amount": 500.00, "simulate_status": "SUCCESS"}'
# Response: {"id": 1, "payment_reference": "PAY-20260930-AB12CD34", "status": "SUCCESS", ...}
```

### Process a Webhook

```bash
curl -X POST http://localhost:8000/api/v1/payments/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "evt-abc123",
    "event_type": "payment.completed",
    "payment_id": "PAY-20260930-AB12CD34",
    "status": "SUCCESS"
  }'
# Response: {"success": true, "event_id": "evt-abc123", "message": "Webhook processed successfully.", ...}
```

### Cancel a Booking

```bash
curl -X POST http://localhost:8000/api/v1/bookings/1/cancel \
  -H "Authorization: Bearer <token>"
# Response: {"id": 1, "booking_reference": "BKG-...", "status": "CANCELLED", "message": "..."}
```

### Error Response Format

All errors follow this envelope:

```json
{
  "success": false,
  "error": {
    "code": "BOOKING_NOT_FOUND",
    "message": "Booking with id=99 was not found."
  }
}
```

---

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `APP_NAME` | Service display name | `EVE Healthcare Diagnostic Service` |
| `APP_ENV` | Environment tag | `development` |
| `SECRET_KEY` | JWT signing key — **must be changed in production** | dev placeholder |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT lifetime in minutes | `60` |
| `ALGORITHM` | JWT algorithm | `HS256` |
| `POSTGRES_SERVER` | DB hostname | `localhost` (Docker: `db`) |
| `POSTGRES_PORT` | DB port | `5432` |
| `POSTGRES_USER` | DB username | `eve_user` |
| `POSTGRES_PASSWORD` | DB password | `eve_password` |
| `POSTGRES_DB` | DB name | `eve_healthcare` |
| `DATABASE_URL` | Full connection URL — overrides POSTGRES_* if set | (assembled) |
| `TEST_DATABASE_URL` | DB used by pytest | `sqlite:///:memory:` |
| `LOG_LEVEL` | Logging verbosity | `INFO` |

---

## Local Setup

### Prerequisites

- Python 3.12+
- PostgreSQL (or use Docker)

### Steps

```bash
# 1. Clone and enter the project
git clone <repo>
cd eve-healthcare-backend

# 2. Create and activate virtual environment
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

# 3. Install all dependencies (including dev)
pip install -e ".[dev]"

# 4. Configure environment
cp .env.example .env
# Edit .env — set DATABASE_URL and a strong SECRET_KEY

# 5. Apply database migrations
alembic upgrade head

# 6. Start the development server
uvicorn app.main:app --reload
```

API docs: http://localhost:8000/docs

---

## Docker Setup

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)

### Quick start

```bash
# 1. Copy and configure environment
cp .env.example .env
# Set a strong SECRET_KEY:
# python -c "import secrets; print(secrets.token_hex(32))"

# 2. Build and start
docker compose up --build
```

This will:
1. Build the API image (multi-stage, `python:3.12-slim`, non-root user)
2. Start `postgres:16-alpine` with a persistent named volume
3. Wait for the DB health check to pass
4. Run `alembic upgrade head` automatically
5. Start Uvicorn on port 8000

| URL | |
|---|---|
| http://localhost:8000/health | Liveness probe |
| http://localhost:8000/docs | Swagger UI |
| http://localhost:8000/redoc | ReDoc |

```bash
# Run in background
docker compose up --build -d

# View logs
docker compose logs -f api

# Stop everything (keep data)
docker compose down

# Stop and delete database volume
docker compose down -v
```

---

## Database Migrations

Migrations live in `alembic/versions/`. The entire schema is in a single initial migration (`001_initial_schema.py`).

```bash
# Apply all pending migrations
alembic upgrade head

# Revert all migrations
alembic downgrade base

# Check current revision
alembic current
```

In Docker, migrations run automatically before Uvicorn starts via the `command` override in `docker-compose.yml`.

---

## Running Tests

Tests use an in-memory SQLite database — **no running PostgreSQL required**.

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=term-missing

# Run a specific test file
pytest tests/test_webhooks.py -v
```

**Test results (last run):** `152 passed, 0 failed, 6 warnings`

### Test coverage by module

| Module | Tests | Key scenarios covered |
|---|---|---|
| `test_health.py` | 9 | Liveness, DB probe, response shape |
| `test_auth.py` | 25 | Signup, login, JWT, duplicate email, password rules |
| `test_centres.py` | 22 | CRUD, filtering, pagination, auth guards |
| `test_tests.py` | 6 | Catalogue management, validation |
| `test_slots.py` | 11 | Slot creation, filters, concurrency |
| `test_bookings.py` | 25 | Full lifecycle, ownership, state guards |
| `test_payments.py` | 20 | Success/fail paths, amount mismatch, idempotency |
| `test_webhooks.py` | 20 | Idempotency (1× / 10×), state transitions, edge cases |
| `test_edge_cases.py` | 6 | Cross-user access, invalid transitions, double-booking |
| `test_models.py` | 8 | DB constraints, Numeric precision, migration syntax |

---

## Edge Cases Handled

| Scenario | Behaviour |
|---|---|
| Duplicate email on signup | 409 `DUPLICATE_USER` |
| Wrong password | 401 `INVALID_CREDENTIALS` |
| Slot booked by two users simultaneously | Row-level lock (SELECT FOR UPDATE); second request gets 409 `SLOT_ALREADY_BOOKED` |
| Payment amount ≠ booking amount | 422 `PAYMENT_AMOUNT_MISMATCH` |
| Payment on confirmed booking | 409 `BOOKING_ALREADY_CONFIRMED` |
| Payment on cancelled/failed booking | 409 with appropriate code |
| `simulate_status: PENDING` supplied | 422 `VALIDATION_ERROR` |
| Duplicate webhook (`event_id` already seen) | 200 `ALREADY_PROCESSED`, no state change |
| Webhook replayed 10× | Only 1 DB event record, idempotent responses |
| Cancelling an already-cancelled booking | 409 `INVALID_STATE_TRANSITION` |
| Accessing another user's booking | 403 `FORBIDDEN` |
| Paying for another user's booking | 403 `FORBIDDEN` |
| Booking a past appointment slot | 422 `PAST_APPOINTMENT_DATE` |
| Booking an inactive test/centre | 422 with descriptive code |
| Invalid resource IDs | 404 with `*_NOT_FOUND` code |
| PENDING supplied to webhook status | 422 `VALIDATION_ERROR` |

---

## Design Decisions

1. **Single migration file**: All tables are created in one `001_initial_schema.py`. For a project of this scope this is cleaner than many small migrations.

2. **Price snapshotting**: `booking.amount` captures `centre_test.price` at the moment of booking creation. Historical bookings are not affected by future price changes.

3. **Centralised state machine**: `BookingService.transition_status` is the single location for all booking state changes. Both the payment service and webhook service call it — no duplicate transition logic exists.

4. **Non-native enums**: SQLAlchemy `native_enum=False` stores enum values as strings, making the schema portable across PostgreSQL and SQLite (used in tests).

5. **Repository layer**: All ORM queries are in `repositories/` rather than in services or routes. This allows services to focus purely on business rules.

6. **Webhook `payment_id` field name**: The webhook schema uses `payment_id` as the field alias for `payment_reference`. This matches common payment gateway conventions while allowing us to resolve by the human-readable reference internally.

7. **No Redis / Celery**: The idempotency requirements are satisfied entirely by a database unique constraint and an application-level pre-check. A task queue would be over-engineering for this scope.

---

## Assumptions

- All authentication is JWT-based; there is no session or refresh-token mechanism.
- The "payment gateway" is fully simulated — `simulate_status` in the request replaces an actual gateway integration.
- An appointment slot is general-purpose (not tied to a specific test) unless a `centre_test_id` is supplied at creation time.
- The cancellation API only supports user-initiated cancellation; automatic expiry of `PENDING` bookings is not implemented.
- Passwords must be at least 8 characters; no additional complexity rules are enforced (beyond what Argon2 requires for hashing).
- A user may attempt multiple payments for a PENDING booking (e.g., after a failed attempt), but only one SUCCESS payment is permitted.

---

## Future Improvements

| Area | Improvement |
|---|---|
| Auth | Refresh tokens, token revocation (Redis allowlist) |
| Auth | Email verification on signup |
| Booking | Automatic expiry of PENDING bookings after a configurable timeout (Celery / APScheduler) |
| Payments | Integration with a real gateway (Stripe / Razorpay) via strategy pattern |
| Search | Full-text search on centre name and test name |
| Observability | Prometheus metrics endpoint, structured JSON logging (e.g. `structlog`) |
| Performance | Connection pooling tuning; read replicas for list endpoints |
| Security | Rate limiting on auth endpoints; HTTPS enforcement |
| Testing | Integration tests against a real PostgreSQL instance in CI |
| CI/CD | GitHub Actions pipeline (lint → test → build image → push) |