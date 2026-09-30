"""Diagnostic Tests catalogue API routes."""

from collections.abc import Sequence

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.diagnostic_test import DiagnosticTestCreate, DiagnosticTestResponse
from app.services.test_service import test_service

router = APIRouter(prefix="/tests", tags=["Diagnostic Tests"])


@router.get(
    "",
    response_model=list[DiagnosticTestResponse],
    status_code=status.HTTP_200_OK,
    summary="List diagnostic tests",
    description="Retrieve a paginated list of diagnostic tests in the catalogue with optional filtering.",
)
def list_tests(
    category: str | None = Query(default=None, description="Filter by test category"),
    is_active: bool | None = Query(default=None, description="Filter by active status"),
    skip: int = Query(default=0, ge=0, description="Number of items to skip"),
    limit: int = Query(default=100, ge=1, le=100, description="Maximum number of items to return"),
    db: Session = Depends(get_db),
) -> Sequence[DiagnosticTestResponse]:
    """Public endpoint to list diagnostic tests in the catalogue."""
    tests = test_service.list_tests(
        db, category=category, is_active=is_active, skip=skip, limit=limit
    )
    return [DiagnosticTestResponse.model_validate(t) for t in tests]


@router.get(
    "/{test_id}",
    response_model=DiagnosticTestResponse,
    status_code=status.HTTP_200_OK,
    summary="Get diagnostic test by ID",
    description="Retrieve detailed information for a specific diagnostic test entry.",
)
def get_test(
    test_id: int = Path(..., ge=1, description="Diagnostic test ID"),
    db: Session = Depends(get_db),
) -> DiagnosticTestResponse:
    """Public endpoint to get a single diagnostic test by ID."""
    test = test_service.get_test(db, test_id)
    return DiagnosticTestResponse.model_validate(test)


@router.post(
    "",
    response_model=DiagnosticTestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create diagnostic test",
    description="Adds a new diagnostic test to the catalogue. Requires authentication.",
)
def create_test(
    test_in: DiagnosticTestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> DiagnosticTestResponse:
    """Protected endpoint to create a new diagnostic test."""
    test = test_service.create_test(db, test_in)
    return DiagnosticTestResponse.model_validate(test)
