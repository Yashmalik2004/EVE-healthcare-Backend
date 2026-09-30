"""FastAPI application factory for the EVE Healthcare Backend.

Design decisions
----------------
* All business logic lives in routers/services — main.py is *wiring only*.
* Global exception handlers normalise every error into a consistent envelope:

    {"success": false, "error": {"code": "...", "message": "..."}}

* CORS is wide-open for development; restrict ``allow_origins`` in production
  via the settings object or an environment variable.

Routes registered here (Phase 1):
    /          — root overview
    /health    — liveness + DB readiness probe

Future routes (added in their respective phases):
    /api/v1/auth          — Phase 2
    /api/v1/centres       — Phase 3
    /api/v1/tests         — Phase 3
    /api/v1/bookings      — Phase 4
    /api/v1/payments      — Phase 5
    /api/v1/webhooks      — Phase 6
"""

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import health
from app.core.config import settings
from app.core.exceptions import AppException
from app.core.logging import logger

# ── OpenAPI tag metadata ──────────────────────────────────────────────────────

tags_metadata = [
    {
        "name": "Health",
        "description": "Service health check and database connectivity verification.",
    },
    # Future phases will extend this list:
    # {"name": "Authentication", ...},
    # {"name": "Diagnostic Centres", ...},
    # {"name": "Diagnostic Tests", ...},
    # {"name": "Bookings", ...},
    # {"name": "Payments", ...},
    # {"name": "Webhooks", ...},
]

# ── Application ───────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.APP_NAME,
    description="Production-grade Modular Backend for Diagnostic Bookings and Payments",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=tags_metadata,
)

# ── Middleware ────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Exception Handlers ────────────────────────────────────────────────────────


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    """Handle known application exceptions with structured error response."""
    logger.warning(f"AppException: [{exc.code}] {exc.message} on path {request.url.path}")
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
    """Handle Pydantic/FastAPI validation errors."""
    errors = exc.errors()
    first_error = errors[0] if errors else {}
    msg = first_error.get("msg", "Validation error.")
    loc = " -> ".join([str(x) for x in first_error.get("loc", [])])
    if loc:
        msg = f"{loc}: {msg}"
    logger.warning(f"Validation error on {request.url.path}: {errors}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "success": False,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": msg,
                "details": errors,
            },
        },
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Handle Starlette HTTP exceptions with named error codes."""
    code = "HTTP_ERROR"
    if exc.status_code == status.HTTP_404_NOT_FOUND:
        code = "RESOURCE_NOT_FOUND"
    elif exc.status_code == status.HTTP_401_UNAUTHORIZED:
        code = "UNAUTHORIZED"
    elif exc.status_code == status.HTTP_403_FORBIDDEN:
        code = "FORBIDDEN"
    elif exc.status_code == status.HTTP_405_METHOD_NOT_ALLOWED:
        code = "METHOD_NOT_ALLOWED"

    logger.warning(
        f"HTTPException [{exc.status_code}]: {exc.detail} on path {request.url.path}"
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
    """Catch-all handler for unexpected exceptions — never leak internal details."""
    logger.exception(f"Unhandled Exception on path {request.url.path}: {exc}")
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
# Future phases will add:
# app.include_router(auth.router, prefix=settings.API_V1_STR)
# app.include_router(centres.router, prefix=settings.API_V1_STR)
# ...


# ── Root overview ─────────────────────────────────────────────────────────────

@app.get("/", tags=["Health"])
def root_overview():
    """Root endpoint — provides service overview and links to documentation."""
    return {
        "service": settings.APP_NAME,
        "environment": settings.APP_ENV,
        "docs_url": "/docs",
        "redoc_url": "/redoc",
        "health_check": "/health",
        "api_v1_prefix": settings.API_V1_STR,
    }
