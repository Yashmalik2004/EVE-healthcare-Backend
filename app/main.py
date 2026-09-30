"""FastAPI application factory for the EVE Healthcare Backend.

Design decisions
----------------
* All business logic lives in routers/services — main.py is *wiring only*.
* Global exception handlers normalise every error into a consistent envelope:

    {"success": false, "error": {"code": "...", "message": "..."}}

* CORS is wide-open for development; restrict ``allow_origins`` in production
  via the settings object or an environment variable.
* An HTTP Bearer security scheme is declared globally so FastAPI auto-generates
  the Swagger "Authorize" button and applies it to all protected routes.
* A lightweight access-log middleware records method, path, status code,
  and response time for every request without touching business logic.

Routes:
    /          — root overview
    /health    — liveness + DB readiness probe

    /api/v1/auth          — Authentication (Phase 3)
    /api/v1/centres       — Diagnostic Centres (Phase 4)
    /api/v1/tests         — Diagnostic Tests (Phase 4)
    /api/v1/bookings      — Booking Engine (Phase 6)
    /api/v1/payments      — Simulated Payments (Phase 7)
    /api/v1/payments/webhook — Payment Webhooks (Phase 8)
"""

import time

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import auth, bookings, centres, health, payments, tests, webhook
from app.core.config import settings
from app.core.exceptions import AppException
from app.core.logging import logger

# ── OpenAPI tag metadata ──────────────────────────────────────────────────────

tags_metadata = [
    {
        "name": "Health",
        "description": (
            "Service liveness probe and database connectivity check. "
            "Returns `healthy` when both the API process and the database are operational, "
            "or `degraded` when the database is unreachable."
        ),
    },
    {
        "name": "Authentication",
        "description": (
            "User registration, JWT login, and profile retrieval. "
            "Use `POST /auth/login` to obtain a Bearer token, then click the "
            "**Authorize** button above and paste the token to authenticate all "
            "protected endpoints."
        ),
    },
    {
        "name": "Diagnostic Centres",
        "description": (
            "Diagnostic centre management, including listing, creation, update, "
            "test-catalogue association, appointment-slot creation, and slot listing."
        ),
    },
    {
        "name": "Diagnostic Tests",
        "description": (
            "Global diagnostic test catalogue — create and look up tests. "
            "Tests are associated with centres via `POST /centres/{id}/tests`."
        ),
    },
    {
        "name": "Bookings",
        "description": (
            "Booking lifecycle management. Creates a booking in **PENDING** state "
            "with atomic row-level slot locking, and transitions it to "
            "**CONFIRMED**, **FAILED**, or **CANCELLED** via the payment and "
            "webhook subsystems."
        ),
    },
    {
        "name": "Payments",
        "description": (
            "Simulated payment processing. `POST /payments` accepts a "
            "`simulate_status` field (SUCCESS | FAILED) to simulate a payment "
            "gateway outcome. Supports optional `Idempotency-Key` header for "
            "safe retries. `POST /payments/webhook` handles inbound gateway "
            "callbacks with strict event-level idempotency."
        ),
    },
]

# ── Application ───────────────────────────────────────────────────────────────

_OPENAPI_DESCRIPTION = """\
## EVE Healthcare Diagnostic Service API

Production-grade backend for diagnostic test booking, payment processing, and
webhook event handling.

### Authentication

Most write endpoints require a JWT Bearer token.

1. Call `POST /api/v1/auth/signup` to register.
2. Call `POST /api/v1/auth/login` to obtain an `access_token`.
3. Click the **Authorize 🔒** button above and enter: `Bearer <your_token>`.

### Error format

All errors are returned as a consistent JSON envelope:

```json
{
  "success": false,
  "error": {
    "code": "DOMAIN_ERROR_CODE",
    "message": "Human-readable description."
  }
}
```

### Pagination

Collection endpoints (`GET /centres`, `GET /tests`, `GET /bookings`,
`GET /centres/{id}/slots`) support `skip` and `limit` query parameters
(default: `skip=0`, `limit=100`, max `limit=100`).
"""

app = FastAPI(
    title=settings.APP_NAME,
    description=_OPENAPI_DESCRIPTION,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=tags_metadata,
    contact={
        "name": "EVE Healthcare Engineering",
    },
    license_info={
        "name": "Proprietary",
    },
)

# ── Security scheme (HTTP Bearer) ─────────────────────────────────────────────
# Registering this makes FastAPI include the securitySchemes block in the
# generated OpenAPI spec and renders the "Authorize" button in Swagger UI.

_bearer_scheme = HTTPBearer(
    scheme_name="BearerAuth",
    description="JWT Bearer token — obtain via POST /api/v1/auth/login",
    auto_error=False,
)


def custom_openapi():
    """Inject the BearerAuth security scheme into the generated OpenAPI spec."""
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=tags_metadata,
    )

    # Add the HTTP Bearer security scheme
    schema.setdefault("components", {}).setdefault("securitySchemes", {})
    schema["components"]["securitySchemes"]["BearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": "Paste the access_token value returned by POST /api/v1/auth/login",
    }

    # Apply BearerAuth as global default security (endpoints can opt out)
    schema["security"] = [{"BearerAuth": []}]

    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi  # type: ignore[method-assign]

# ── Middleware ────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def access_log_middleware(request: Request, call_next):
    """Log every incoming request with method, path, status code, and latency.

    Sensitive paths (e.g. /auth/login, /auth/signup) have their bodies omitted
    from logs entirely — only the path and outcome are recorded.
    """
    start_time = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start_time) * 1000, 1)

    logger.info(
        f"{request.method} {request.url.path} → {response.status_code} "
        f"({duration_ms}ms)"
    )
    return response


# ── Exception Handlers ────────────────────────────────────────────────────────


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    """Handle known application exceptions with structured error response.

    All domain exceptions (NotFoundException, ForbiddenException, etc.) extend
    AppException and are serialised into the standard error envelope here,
    keeping error-handling logic out of individual route handlers.
    """
    logger.warning(
        f"AppException [{exc.status_code}] [{exc.code}]: {exc.message} "
        f"— {request.method} {request.url.path}"
    )
    content: dict = {
        "success": False,
        "error": {
            "code": exc.code,
            "message": exc.message,
        },
    }
    if exc.details is not None:
        content["error"]["details"] = exc.details
    return JSONResponse(status_code=exc.status_code, content=content, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle Pydantic/FastAPI schema validation errors.

    Returns HTTP 422 with a ``VALIDATION_ERROR`` code and a human-readable
    message derived from the first validation failure.  The full error list
    is included under ``details`` for debugging.
    """
    raw_errors = exc.errors()
    first_error = raw_errors[0] if raw_errors else {}
    msg = first_error.get("msg", "Validation error.")
    loc = " -> ".join([str(x) for x in first_error.get("loc", [])])
    if loc:
        msg = f"{loc}: {msg}"
    logger.warning(
        f"Validation error — {request.method} {request.url.path}: "
        f"{len(raw_errors)} error(s)"
    )
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": msg,
                "details": jsonable_encoder(raw_errors),
            },
        },
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Handle Starlette HTTP exceptions with domain-aligned error codes.

    Maps common HTTP status codes to meaningful error code strings so clients
    don't need to inspect numeric status codes to identify the error class.
    """
    status_to_code: dict[int, str] = {
        status.HTTP_400_BAD_REQUEST: "BAD_REQUEST",
        status.HTTP_401_UNAUTHORIZED: "UNAUTHORIZED",
        status.HTTP_403_FORBIDDEN: "FORBIDDEN",
        status.HTTP_404_NOT_FOUND: "RESOURCE_NOT_FOUND",
        status.HTTP_405_METHOD_NOT_ALLOWED: "METHOD_NOT_ALLOWED",
        status.HTTP_409_CONFLICT: "CONFLICT",
        status.HTTP_422_UNPROCESSABLE_CONTENT: "VALIDATION_ERROR",
    }
    code = status_to_code.get(exc.status_code, "HTTP_ERROR")

    logger.warning(
        f"HTTPException [{exc.status_code}] [{code}]: {exc.detail} "
        f"— {request.method} {request.url.path}"
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": {
                "code": code,
                "message": str(exc.detail),
            },
        },
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all handler for unexpected exceptions.

    Logs the full traceback server-side but never leaks internal details to
    the client — only a generic ``INTERNAL_SERVER_ERROR`` code is returned.
    """
    logger.exception(
        f"Unhandled exception — {request.method} {request.url.path}: "
        f"{type(exc).__name__}: {exc}"
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred. Please try again later.",
            },
        },
    )


# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(health.router)
app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(centres.router, prefix=settings.API_V1_STR)
app.include_router(tests.router, prefix=settings.API_V1_STR)
app.include_router(bookings.router, prefix=settings.API_V1_STR)
app.include_router(payments.router, prefix=settings.API_V1_STR)
app.include_router(webhook.router, prefix=settings.API_V1_STR)


# ── Root overview ─────────────────────────────────────────────────────────────

@app.get(
    "/",
    tags=["Health"],
    summary="Service overview",
    description="Returns service metadata and links to documentation and health-check endpoints.",
)
def root_overview():
    """Root endpoint — service metadata and documentation links."""
    return {
        "service": settings.APP_NAME,
        "version": "1.0.0",
        "environment": settings.APP_ENV,
        "docs_url": "/docs",
        "redoc_url": "/redoc",
        "openapi_url": "/openapi.json",
        "health_check": "/health",
        "api_v1_prefix": settings.API_V1_STR,
    }
