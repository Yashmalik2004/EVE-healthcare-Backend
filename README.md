# EVE Healthcare Backend

Production-grade FastAPI backend for diagnostic test bookings and payments.

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | FastAPI 0.115+ |
| ORM | SQLAlchemy 2.0 |
| Migrations | Alembic |
| Database | PostgreSQL (prod) / SQLite (tests) |
| Validation | Pydantic v2 + pydantic-settings |
| Auth | PyJWT + argon2-cffi |
| Testing | pytest + httpx |
| Container | Docker + Docker Compose |

---

## Running with Docker (recommended)

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (includes Docker Compose v2)

### 1. Copy the environment template

```bash
cp .env.example .env
```

> **Important**: Replace `SECRET_KEY` with a strong random value before running in any shared environment.
> You can generate one with: `python -c "import secrets; print(secrets.token_hex(32))"`

### 2. Start all services

```bash
docker compose up --build
```

This single command will:

1. Build the application image from the `Dockerfile`
2. Start a `postgres:16-alpine` database container
3. Wait for the database to pass its health check
4. Run `alembic upgrade head` to apply all migrations automatically
5. Start the Uvicorn server on **http://localhost:8000**

### 3. Verify the deployment

| URL | Description |
|---|---|
| http://localhost:8000/health | Liveness + DB readiness probe |
| http://localhost:8000/docs | Interactive Swagger UI |
| http://localhost:8000/redoc | ReDoc documentation |

### Useful Docker commands

```bash
# Run in detached mode
docker compose up --build -d

# View live logs
docker compose logs -f api

# Stop all services
docker compose down

# Stop and remove volumes (⚠️ deletes database data)
docker compose down -v

# Re-run migrations manually (services must be running)
docker compose exec api alembic upgrade head
```

---

## Local Setup (without Docker)

### 1. Create virtual environment

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -e ".[dev]"
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env — set DATABASE_URL to point at your local PostgreSQL instance
```

### 4. Run migrations

```bash
alembic upgrade head
```

### 5. Start the development server

```bash
uvicorn app.main:app --reload
```

API docs available at: http://localhost:8000/docs

---

## Running Tests

Tests use an in-memory SQLite database — no running Postgres required.

```bash
pytest
# With coverage report
pytest --cov=app --cov-report=term-missing
```

---

## Project Structure

```
eve-healthcare-backend/
├── app/
│   ├── api/
│   │   └── routes/       # FastAPI route handlers
│   ├── core/
│   │   ├── config.py     # Settings (pydantic-settings)
│   │   ├── exceptions.py # AppException hierarchy
│   │   └── logging.py    # Structured logging
│   ├── db/
│   │   └── database.py   # Engine, session, Base, get_db
│   ├── models/           # SQLAlchemy ORM models
│   ├── repositories/     # Data access layer
│   ├── schemas/          # Pydantic request/response models
│   ├── services/         # Business logic layer
│   └── main.py           # FastAPI app factory
├── alembic/              # Database migrations
├── tests/                # pytest test suite
├── .env.example          # Environment variable template
├── Dockerfile            # Multi-stage production image
├── docker-compose.yml    # Compose: api + db services
├── alembic.ini
└── pyproject.toml
```

---

## API Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/` | — | Service overview |
| GET | `/health` | — | Liveness + DB readiness probe |
| GET | `/docs` | — | Swagger UI |
| POST | `/api/v1/auth/signup` | — | Register a new user |
| POST | `/api/v1/auth/login` | — | Obtain JWT token |
| GET | `/api/v1/auth/me` | ✅ | Current user profile |
| GET | `/api/v1/centres` | — | List diagnostic centres |
| POST | `/api/v1/centres` | ✅ | Create a centre |
| GET | `/api/v1/centres/{id}/slots` | — | List appointment slots |
| POST | `/api/v1/centres/{id}/slots` | ✅ | Create appointment slot |
| GET | `/api/v1/tests` | — | List diagnostic tests |
| POST | `/api/v1/tests` | ✅ | Create diagnostic test |
| GET | `/api/v1/bookings` | ✅ | List user bookings |
| POST | `/api/v1/bookings` | ✅ | Create booking |
| GET | `/api/v1/bookings/{id}` | ✅ | Get booking detail |
| POST | `/api/v1/bookings/{id}/cancel` | ✅ | Cancel booking |
| POST | `/api/v1/payments` | ✅ | Create payment |
| GET | `/api/v1/payments/{id}` | ✅ | Get payment detail |
| POST | `/api/v1/payments/webhook` | — | Payment gateway callback |

---

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `APP_ENV` | Environment name | `development` |
| `SECRET_KEY` | JWT signing key | ⚠️ must change in production |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT expiry | `60` |
| `POSTGRES_SERVER` | DB host | `localhost` (Docker: `db`) |
| `POSTGRES_USER` | DB username | `eve_user` |
| `POSTGRES_PASSWORD` | DB password | `eve_password` |
| `POSTGRES_DB` | Database name | `eve_healthcare` |
| `DATABASE_URL` | Full PostgreSQL URL (overrides above) | assembled from POSTGRES_* |
| `LOG_LEVEL` | Logging verbosity | `INFO` |