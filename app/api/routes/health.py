"""Health-check endpoint.

Provides a lightweight liveness probe (GET /health) that:
1. Confirms the FastAPI process is running.
2. Runs a minimal database connectivity check (SELECT 1).

The overall status is reported as "healthy" only when both the application
and the database are operational.  A database failure degrades the status to
"degraded" without raising an HTTP error, so upstream load-balancers can
distinguish between a dead process and a temporarily degraded service.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db

router = APIRouter(tags=["Health"])


@router.get("/health", status_code=status.HTTP_200_OK)
def health_check(db: Session = Depends(get_db)):
    """Health check endpoint — confirms API process is up and DB is reachable."""
    db_status = "healthy"
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_status = "unhealthy"

    return {
        "status": "healthy" if db_status == "healthy" else "degraded",
        "app_name": settings.APP_NAME,
        "environment": settings.APP_ENV,
        "database": db_status,
        "timestamp": datetime.now(UTC).isoformat(),
    }
