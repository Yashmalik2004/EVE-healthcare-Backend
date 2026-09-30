"""Health-check endpoint.

Provides a lightweight liveness probe (GET /health) that:
1. Confirms the FastAPI process is running.
2. Runs a minimal database connectivity check (SELECT 1).

The overall status is reported as "healthy" only when both the application
and the database are operational. A database failure degrades the status to
"degraded" without raising an unhandled HTTP 500, so upstream load-balancers
can distinguish between a dead process and a temporarily degraded dependency.
No database connection strings, credentials, or internal IPs are ever exposed.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.schemas.health import HealthResponse

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Service health check",
    description=(
        "Liveness and readiness probe checking API service availability and database connectivity. "
        "Returns 'healthy' when all subsystems are operational, or 'degraded' if database is unreachable. "
        "Never exposes database credentials or internal infrastructure details."
    ),
)
def health_check(db: Session = Depends(get_db)) -> HealthResponse:
    """Health check endpoint checking application and database status."""
    db_status = "healthy"
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_status = "unhealthy"

    return HealthResponse(
        status="healthy" if db_status == "healthy" else "degraded",
        app_name=settings.APP_NAME,
        environment=settings.APP_ENV,
        database=db_status,
        version="1.0.0",
        api_version=settings.API_V1_STR,
        timestamp=datetime.now(UTC).isoformat(),
    )
