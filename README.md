# EVE Healthcare 
# Diagnostic Booking & Payment Backend

A production-oriented REST API for diagnostic test booking, simulated payments, idempotent payment webhooks, authentication, rate limiting, and appointment-slot management.

Built for the **EVE Healthcare SDE Intern / Backend Engineering Assessment**.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Core Features](#2-core-features)
3. [Architecture](#3-architecture)
4. [Tech Stack](#4-tech-stack)
5. [Project Structure](#5-project-structure)
6. [Database Design](#6-database-design)
7. [Booking State Machine](#7-booking-state-machine)
8. [Payment & Idempotency](#8-payment--idempotency)
9. [Webhook Idempotency](#9-webhook-idempotency)
10. [Authentication & Authorization](#10-authentication--authorization)
11. [Rate Limiting](#11-rate-limiting)
12. [API Endpoints](#12-api-endpoints)
13. [Environment Variables](#13-environment-variables)
14. [Local Setup — Recommended Docker Method](#14-local-setup--recommended-docker-method)
15. [Local Setup — Without Docker](#15-local-setup--without-docker)
16. [Database Migrations](#16-database-migrations)
17. [Running Tests](#17-running-tests)
18. [Manual API Testing](#18-manual-api-testing)
19. [Edge Cases & Error Handling](#19-edge-cases--error-handling)
20. [Design Decisions](#20-design-decisions)
21. [Assumptions](#21-assumptions)
22. [Future Improvements](#22-future-improvements)

---

## 1. Overview

The service manages the lifecycle of a diagnostic test booking:

1. A patient registers and authenticates using JWT.
2. The patient can browse diagnostic centres and their available tests.
3. Centre-specific test pricing is maintained through centre/test associations.
4. Appointment slots are created for future appointments.
5. A booking atomically reserves an available slot and snapshots the current price.
6. A simulated payment processes the booking as `SUCCESS` or `FAILED`.
7. Payment webhooks can update payment and booking state while remaining strictly idempotent.
8. Redis-backed rate limiting protects selected API operations.

The design prioritizes correctness around:

- Price integrity
- Slot reservation
- Booking state transitions
- Payment amount validation
- Payment idempotency
- Webhook idempotency
- Authentication and resource ownership
- Database consistency

---

## 2. Core Features

### Authentication & Security

- JWT bearer authentication
- Argon2 password hashing
- Configurable JWT expiration
- PATIENT / ADMIN roles
- Resource ownership checks
- Protected booking and payment operations
- Validation of invalid and missing JWTs
- Consistent application error responses

### Diagnostic Centres & Tests

- Diagnostic centre management
- Diagnostic test catalogue
- Centre-specific test pricing
- Centre/test availability
- Appointment slot management
- Future-date validation
- Filtering and pagination on supported list endpoints

### Booking Engine

- Booking creation in `PENDING` state
- Atomic appointment-slot reservation
- Price snapshot at booking time
- Duplicate slot protection
- Booking ownership enforcement
- Booking cancellation
- Explicit booking state machine

### Payments

- Simulated `SUCCESS` / `FAILED` payment processing
- Booking amount validation
- Payment records with provider/reference information
- Client-supplied `Idempotency-Key`
- Duplicate payment protection
- Booking/payment state synchronization

### Webhooks

- Payment webhook endpoint
- Event-level idempotency
- Database-level unique constraint on webhook event IDs
- Safe duplicate event handling
- Atomic payment + booking + webhook-event updates

### Rate Limiting

Redis-backed rate limiting is applied to selected endpoints:

| Operation | Limit |
|---|---:|
| Signup | 3 requests/minute/IP |
| Login | 5 requests/minute/IP |
| Payments | 10 requests/minute/user |
| Webhooks | 30 requests/minute/IP |

Rate-limit responses expose:

- `X-RateLimit-Limit`
- `X-RateLimit-Remaining`
- `X-RateLimit-Reset`
- `Retry-After`

If Redis becomes unavailable, the rate limiter fails open and logs the condition so that Redis availability does not take the API down.

### Engineering

- FastAPI OpenAPI/Swagger documentation
- SQLAlchemy ORM
- Alembic migrations
- PostgreSQL
- SQLite-based automated test database
- Docker Compose
- Redis
- Structured logging
- Automated tests
- Health endpoint

---

## 3. Architecture

The application follows a layered modular-monolith architecture:

```text
                    HTTP Request
                         │
                         ▼
              ┌─────────────────────┐
              │   FastAPI Routers   │
              │ HTTP / Auth / Docs  │
              └──────────┬──────────┘
                         │
                         ▼
              ┌─────────────────────┐
              │    Pydantic         │
              │ Validation Schemas  │
              └──────────┬──────────┘
                         │
                         ▼
              ┌─────────────────────┐
              │   Service Layer     │
              │ Business Rules      │
              │ State Transitions   │
              └──────────┬──────────┘
                         │
                         ▼
              ┌─────────────────────┐
              │ Repository Layer    │
              │ Database Access     │
              └──────────┬──────────┘
                         │
                         ▼
              ┌─────────────────────┐
              │ SQLAlchemy / DB     │
              │ PostgreSQL          │
              └─────────────────────┘

                     ┌─────────┐
                     │ Redis   │
                     │ Rate    │
                     │ Limiter │
                     └─────────┘
```

### Architectural principles

- Routes remain thin and delegate business logic to services.
- Business rules are centralized in service classes.
- Database access is separated into repositories.
- Pydantic schemas handle request/response validation.
- Booking state changes go through explicit transition rules.
- Financial values use decimal/numeric types rather than floating-point arithmetic.
- Database constraints provide the final layer of idempotency and integrity.

---

## 4. Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| Framework | FastAPI |
| ORM | SQLAlchemy 2.0 |
| Database | PostgreSQL 16 |
| Test Database | SQLite |
| Migrations | Alembic |
| Validation | Pydantic v2 / pydantic-settings |
| Authentication | PyJWT / JWT HS256 |
| Password Hashing | Argon2 |
| Rate Limiting | Redis |
| Testing | pytest / HTTPX / pytest-cov |
| Containerization | Docker / Docker Compose |
| API Documentation | OpenAPI / Swagger UI |
| Server | Uvicorn |

---

## 5. Project Structure

```text
eve-healthcare-backend/
├── app/
│   ├── api/
│   │   ├── deps.py
│   │   └── routes/
│   │       ├── auth.py
│   │       ├── centres.py
│   │       ├── tests.py
│   │       ├── bookings.py
│   │       ├── payments.py
│   │       ├── webhooks.py
│   │       └── health.py
│   │
│   ├── core/
│   │   ├── config.py
│   │   ├── exceptions.py
│   │   ├── logging.py
│   │   └── security.py
│   │
│   ├── db/
│   │   ├── database.py
│   │   └── models/
│   │
│   ├── repositories/
│   ├── schemas/
│   ├── services/
│   └── main.py
│
├── alembic/
│   ├── versions/
│   ├── env.py
│   └── script.py.mako
│
├── tests/
├── Dockerfile
├── docker-compose.yml
├── alembic.ini
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## 6. Database Design

The main entities are:

```text
users
  │
  └────────────── bookings
                       │
                       ├──────── centre_tests ───── diagnostic_tests
                       │
                       ├──────── appointment_slots
                       │
                       └──────── payments
                                      │
                                      └──── payment_webhook_events

diagnostic_centres
        │
        ├──────── centre_tests
        │
        └──────── appointment_slots
```

### Main tables

#### `users`

```text
id
email UNIQUE
password_hash
full_name
role
is_active
created_at
updated_at
```

#### `diagnostic_centres`

```text
id
name
address
city
state
latitude
longitude
is_active
created_at
updated_at
```

#### `diagnostic_tests`

```text
id
name
description
category
is_active
created_at
updated_at
```

#### `centre_tests`

Represents the test offered by a specific centre.

```text
id
centre_id FK
test_id FK
price NUMERIC(10,2)
is_available
created_at
updated_at
```

A centre/test mapping is unique.

#### `appointment_slots`

```text
id
centre_id FK
centre_test_id FK
appointment_datetime
is_available
created_at
```

#### `bookings`

```text
id
booking_reference UNIQUE
user_id FK
centre_test_id FK
appointment_slot_id FK
amount NUMERIC(10,2)
status
created_at
updated_at
```

`amount` is a price snapshot captured when the booking is created.

#### `payments`

```text
id
payment_reference UNIQUE
booking_id FK
amount NUMERIC(10,2)
status
provider
provider_transaction_id
idempotency_key UNIQUE
created_at
updated_at
```

#### `payment_webhook_events`

```text
id
event_id UNIQUE
event_type
payment_id / payment_reference
payload
processed_at
created_at
```

### Database integrity

- Monetary values use `NUMERIC(10,2)` / `Decimal`.
- User emails are unique.
- Centre/test mappings are unique.
- Booking references are unique.
- Payment references and idempotency keys are unique.
- Webhook event IDs are unique.
- Foreign keys protect booking/payment audit records.

---

## 7. Booking State Machine

```text
                   Booking Created
                         │
                         ▼
                     PENDING
                    /       \
                   /         \
        Payment SUCCESS     Payment FAILED
                 │               │
                 ▼               ▼
             CONFIRMED        FAILED
                 │
                 │
             Cancellation
                 │
                 ▼
             CANCELLED
```

### Rules

- New bookings start as `PENDING`.
- Successful payment moves `PENDING → CONFIRMED`.
- Failed payment moves `PENDING → FAILED`.
- Cancellation moves the booking to `CANCELLED`.
- `FAILED` and `CANCELLED` are terminal states.
- Invalid state transitions are rejected.
- Failed/cancelled bookings release the reserved slot.

---

## 8. Payment & Idempotency

`POST /api/v1/payments` accepts:

```json
{
  "booking_id": 1,
  "amount": 500,
  "simulate_status": "SUCCESS"
}
```

An optional header can be supplied:

```text
Idempotency-Key: payment-test-001
```

### Processing flow

```text
Request
   │
   ▼
Check Idempotency-Key
   │
   ├── Existing → return existing payment
   │
   ▼
Load booking
   │
   ▼
Verify ownership
   │
   ▼
Verify booking is PENDING
   │
   ▼
Verify amount == booking.amount
   │
   ▼
Create payment
   │
   ▼
Transition booking
   │
   ▼
Commit transaction
```

The client cannot change the authoritative booking price by supplying a different payment amount.

---

## 9. Webhook Idempotency

Webhook endpoint:

```text
POST /api/v1/payments/webhook
```

Example:

```json
{
  "event_id": "evt-abc123",
  "event_type": "payment.completed",
  "payment_id": "PAY-20261001-C5492D23",
  "status": "SUCCESS"
}
```

### Two-layer idempotency

**Layer 1 — Application check**

The service first checks whether `event_id` has already been processed.

If found, it returns an already-processed response without repeating the state change.

**Layer 2 — Database constraint**

`payment_webhook_events.event_id` is unique.

If two identical events arrive concurrently, the database constraint prevents two event records from being inserted.

Payment status, booking state, and webhook-event persistence are handled transactionally.

---

## 10. Authentication & Authorization

### Authentication

- Passwords are hashed using Argon2.
- Login returns a JWT access token.
- JWT uses the configured signing secret and algorithm.
- Token expiration is configurable.

Example token usage:

```text
Authorization: Bearer <JWT_TOKEN>
```

### Authorization

- Patients can access their own protected booking/payment resources.
- Admin users can access broader administrative resources where supported.
- Protected endpoints reject missing or invalid JWTs.
- Signup creates a normal patient account; role escalation is not accepted from the public signup request.

---

## 11. Rate Limiting

Redis is used as the backing store for endpoint rate limits.

| Endpoint category | Limit |
|---|---:|
| Signup | 3/minute/IP |
| Login | 5/minute/IP |
| Payments | 10/minute/user |
| Webhook | 30/minute/IP |

Example rate-limit response headers:

```text
X-RateLimit-Limit: 5
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 43
Retry-After: 43
```

A rate-limited request returns:

```text
429 Too Many Requests
```

The limiter is designed to fail open if Redis is unavailable, while logging the Redis failure.

---

## 12. API Endpoints

### Health

| Method | Endpoint | Auth |
|---|---|---|
| GET | `/` | No |
| GET | `/health` | No |

### Authentication

| Method | Endpoint | Auth |
|---|---|---|
| POST | `/api/v1/auth/signup` | No |
| POST | `/api/v1/auth/login` | No |
| GET | `/api/v1/auth/me` | Yes |

### Diagnostic Centres

| Method | Endpoint | Auth |
|---|---|---|
| GET | `/api/v1/centres` | No |
| POST | `/api/v1/centres` | Yes |
| GET | `/api/v1/centres/{id}` | No |
| PATCH | `/api/v1/centres/{id}` | Yes |
| GET | `/api/v1/centres/{id}/tests` | No |
| POST | `/api/v1/centres/{id}/tests` | Yes |
| GET | `/api/v1/centres/{id}/slots` | No |
| POST | `/api/v1/centres/{id}/slots` | Yes |

### Diagnostic Tests

| Method | Endpoint | Auth |
|---|---|---|
| GET | `/api/v1/tests` | No |
| POST | `/api/v1/tests` | Yes |
| GET | `/api/v1/tests/{id}` | No |

### Bookings

| Method | Endpoint | Auth |
|---|---|---|
| POST | `/api/v1/bookings` | Yes |
| GET | `/api/v1/bookings` | Yes |
| GET | `/api/v1/bookings/{id}` | Yes |
| POST | `/api/v1/bookings/{id}/cancel` | Yes |

### Payments

| Method | Endpoint | Auth |
|---|---|---|
| POST | `/api/v1/payments` | Yes |
| GET | `/api/v1/payments/{id}` | Yes |
| POST | `/api/v1/payments/webhook` | No |

---

## 13. Environment Variables

The repository contains `.env.example`.

Create your local `.env` from it.

| Variable | Example / Default | Purpose |
|---|---|---|
| `APP_NAME` | `EVE Healthcare Diagnostic Service` | Application name |
| `APP_ENV` | `development` | Environment |
| `DEBUG` | `true` | Debug mode |
| `API_V1_STR` | `/api/v1` | API prefix |
| `SECRET_KEY` | change locally | JWT signing key |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | JWT lifetime |
| `ALGORITHM` | `HS256` | JWT algorithm |
| `POSTGRES_SERVER` | `localhost` / `db` in Docker | PostgreSQL host |
| `POSTGRES_PORT` | `5432` | PostgreSQL port |
| `POSTGRES_USER` | `eve_user` | DB user |
| `POSTGRES_PASSWORD` | `eve_password` | DB password |
| `POSTGRES_DB` | `eve_healthcare` | DB name |
| `DATABASE_URL` | PostgreSQL connection URL | Database connection |
| `TEST_DATABASE_URL` | `sqlite:///./test.db` | Test database |
| `LOG_LEVEL` | `INFO` | Logging level |

Do not commit `.env` or production secrets.

---

## 14. Local Setup — Recommended Docker Method

This is the **recommended method for an evaluator/instructor** because it avoids requiring a separate PostgreSQL and Redis installation.

### Prerequisites

Install:

- Git
- Docker Desktop

Make sure Docker Desktop is running.

### Step 1 — Clone the repository

```bash
git clone https://github.com/Yashmalik2004/EVE-healthcare-Backend.git
cd eve-healthcare-backend
```

### Step 2 — Create the environment file

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Linux/macOS:

```bash
cp .env.example .env
```

Open `.env` and set a local secret key.

Generate one with Python:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Copy the generated value into:

```env
SECRET_KEY=<generated-secret>
```

For Docker, use the Compose service name for PostgreSQL:

```env
POSTGRES_SERVER=db
POSTGRES_PORT=5432
POSTGRES_USER=eve_user
POSTGRES_PASSWORD=eve_password
POSTGRES_DB=eve_healthcare
DATABASE_URL=postgresql://eve_user:eve_password@db:5432/eve_healthcare
```

If the `.env.example` contains Redis settings, use the Compose service name:

```env
REDIS_HOST=redis
REDIS_PORT=6379
```

### Step 3 — Build and start everything

```bash
docker compose up --build
```

Docker Compose starts:

```text
API        → localhost:8000
PostgreSQL → localhost:5432
Redis      → localhost:6379
```

The API container waits for PostgreSQL to become healthy, applies Alembic migrations, and starts Uvicorn.

### Step 4 — Verify containers

Open another terminal:

```bash
docker compose ps
```

Expected services:

```text
api      Up / healthy
db       Up / healthy
redis    Up / healthy
```

### Step 5 — Verify the API

Health endpoint:

```text
http://localhost:8000/health
```

Swagger:

```text
http://localhost:8000/docs
```

ReDoc:

```text
http://localhost:8000/redoc
```

### Step 6 — Test the application through Swagger

Open:

```text
http://localhost:8000/docs
```

Recommended evaluation flow:

1. `POST /api/v1/auth/signup`
2. `POST /api/v1/auth/login`
3. Copy the returned JWT.
4. Click **Authorize** in Swagger.
5. Paste the JWT token.
6. Create/view a diagnostic centre.
7. Create/view a diagnostic test.
8. Associate the test with the centre and set its price.
9. Create an appointment slot.
10. Create a booking.
11. Process a simulated payment.
12. Verify the booking becomes `CONFIRMED`.
13. Verify the payment record.
14. Test the payment idempotency key.
15. Inspect `/health`.

### Step 7 — Stop the application

```bash
docker compose down
```

This stops the containers while preserving the PostgreSQL named volume.

To stop everything and delete the database volume/data:

```bash
docker compose down -v
```

---

## 15. Local Setup — Without Docker

Docker is recommended, but the application can also be run directly.

### Prerequisites

- Python 3.12+
- PostgreSQL 16
- Redis

### Step 1 — Clone

```bash
git clone https://github.com/Yashmalik2004/EVE-healthcare-Backend.git
cd eve-healthcare-backend
```

### Step 2 — Create virtual environment

Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Step 3 — Install dependencies

```bash
pip install -r requirements.txt
```

### Step 4 — Configure `.env`

Windows:

```powershell
Copy-Item .env.example .env
```

Linux/macOS:

```bash
cp .env.example .env
```

Set the PostgreSQL connection to your local PostgreSQL instance:

```env
POSTGRES_SERVER=localhost
POSTGRES_PORT=5432
POSTGRES_USER=eve_user
POSTGRES_PASSWORD=eve_password
POSTGRES_DB=eve_healthcare
DATABASE_URL=postgresql://eve_user:eve_password@localhost:5432/eve_healthcare
```

Start Redis separately and configure its host/port according to the application's `.env.example`.

### Step 5 — Create the PostgreSQL database

Create:

```text
Database: eve_healthcare
User: eve_user
Password: eve_password
```

The PostgreSQL server must be running before migrations are applied.

### Step 6 — Apply migrations

```bash
alembic upgrade head
```

### Step 7 — Start the API

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open:

```text
http://localhost:8000/docs
```

---

## 16. Database Migrations

Apply the latest migrations:

```bash
alembic upgrade head
```

Check the current revision:

```bash
alembic current
```

Rollback one migration:

```bash
alembic downgrade -1
```

Create a new migration after model changes:

```bash
alembic revision --autogenerate -m "describe_change"
```

With Docker Compose, migrations are executed automatically when the API container starts.

---

## 17. Running Tests

The automated tests are designed to run against the configured test database and remain isolated from the development database.

Activate the virtual environment if running outside Docker:

```powershell
.\.venv\Scripts\Activate.ps1
```

Run the complete suite:

```bash
pytest -v
```

Run with coverage:

```bash
pytest --cov=app
```

Run a specific test module:

```bash
pytest tests/test_webhooks.py -v
```

### Current verification

The project was verified locally with:

```text
164 passed
```

The coverage test suite also completed successfully.

---

## 18. Manual API Testing

Swagger UI:

```text
http://localhost:8000/docs
```

A typical manual flow is:

### 1. Signup

```http
POST /api/v1/auth/signup
```

```json
{
  "email": "yash@gmail.com",
  "password": "12345678",
  "full_name": "Yash Malik"
}
```

### 2. Login

```http
POST /api/v1/auth/login
```

Use the returned JWT with Swagger's **Authorize** button. ( in 2nd field -> BearerAuth  (http, Bearer) )

### 3. Create a centre

```http
POST /api/v1/centres
```

### 4. Create a diagnostic test

```http
POST /api/v1/tests
```

### 5. Associate test with centre

```http
POST /api/v1/centres/{centre_id}/tests
```

Example:

```json
{
  "test_id": 2,
  "price": 500
}
```

### 6. Create appointment slot

```http
POST /api/v1/centres/{centre_id}/slots
```

Example:

```json
{
  "centre_test_id": 1,
  "appointment_datetime": "2026-10-03T17:50:14.707Z",
  "is_available": true
}
```

### 7. Create booking

```http
POST /api/v1/bookings
```

Example:

```json
{
  "centre_test_id": 1,
  "appointment_slot_id": 1
}
```

### 8. Process payment

```http
POST /api/v1/payments
```

Example:

```json
{
  "booking_id": 1,
  "amount": 500,
  "simulate_status": "SUCCESS"
}
```

Header:

```text
Idempotency-Key: payment-test-001
```

### 9. Verify booking

```http
GET /api/v1/bookings/1
```

A successful payment should result in:

```text
status: CONFIRMED
```

### 10. Verify payment

```http
GET /api/v1/payments/1
```

---

## 19. Edge Cases & Error Handling

| Scenario | Expected behavior |
|---|---|
| Duplicate signup | Rejected |
| Invalid email/password input | Validation error |
| Wrong credentials | `401 Unauthorized` |
| Invalid/missing JWT | `401 Unauthorized` |
| Invalid resource ID | `404 Not Found` |
| Duplicate centre/test association | Rejected |
| Negative centre-test price | Validation error |
| Invalid centre/test relationship | Rejected |
| Past appointment slot | Rejected |
| Double booking | Rejected |
| Payment amount mismatch | Rejected |
| Duplicate payment idempotency key | Existing payment returned |
| Payment for invalid booking | Rejected |
| Payment for unauthorized booking | Rejected |
| Payment for completed booking | Rejected |
| Duplicate webhook event | Existing event recognized |
| Invalid webhook event | Rejected |
| Invalid booking state transition | Rejected |
| Missing authentication | `401 Unauthorized` |
| Rate-limit exceeded | `429 Too Many Requests` |

---

## 20. Design Decisions

### Modular monolith

A modular monolith keeps domain boundaries clear without introducing unnecessary distributed-system complexity for this assessment.

### Price snapshotting

`booking.amount` stores the price at booking time. Later changes to a centre's price do not alter historical bookings.

### Centralized booking state transitions

Booking status changes are handled through a centralized state machine so payment and webhook flows do not implement conflicting transition logic.

### Database-backed idempotency

Payment idempotency keys and webhook event IDs are backed by unique database constraints. This makes the database the final guard against duplicate processing.

### PostgreSQL for application data

PostgreSQL provides transactional guarantees, foreign keys, unique constraints, and row-level locking required for reliable booking/payment behavior.

### Redis for rate limiting

Redis provides shared rate-limit state across API instances while keeping rate-limiting concerns separate from relational business data.

### SQLite for tests

SQLite keeps the automated suite fast and isolated from the developer's PostgreSQL instance.

---

## 21. Assumptions

- Authentication uses JWT; there is no refresh-token mechanism.
- Payment processing is simulated; no real payment gateway is connected.
- `simulate_status` represents the simulated gateway outcome.
- Appointment timestamps are handled as UTC timestamps.
- Booking amount is a snapshot of the centre/test price at booking creation.
- A booking initially enters `PENDING`.
- Successful payment confirms the booking.
- Failed payment results in a failed booking and releases the reserved slot.
- Cancelled/failed bookings release their appointment slot.
- Rate limiting is infrastructure protection and does not replace authentication/authorization.
- Redis is used for rate limiting; core relational application data remains in PostgreSQL.

---

## 22. Future Improvements

Potential production extensions include:

- Refresh tokens and token revocation
- Email verification
- Automatic expiry of pending bookings
- Real payment gateway integration such as Stripe/Razorpay
- Celery/Redis background jobs for asynchronous processing
- Webhook retry queues with exponential backoff
- Prometheus metrics
- Distributed locking for multi-instance deployments
- Full-text search
- PostgreSQL integration tests in CI
- GitHub Actions CI/CD
- Connection-pool tuning and read replicas
- HTTPS enforcement and production secret management
- PDF diagnostic report generation

---

## Submission Checklist

Before submitting the repository:

```bash
pytest -v
pytest --cov=app
docker compose config
docker compose ps
git status
```

Confirm:

- `.env` is not committed.
- Secrets are not committed.
- Tests pass.
- Docker Compose starts API, PostgreSQL, and Redis.
- Alembic migrations run successfully.
- Swagger opens at `/docs`.
- `/health` responds successfully.
- README setup instructions match the repository.
- Git history contains your implementation rather than copied history from another candidate/reference repository.

---

## License

This project was developed as part of the EVE Healthcare SDE Intern Backend Engineering Assessment.
