"""Diagnostic Centres API routes."""

from collections.abc import Sequence

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.centre import CentreCreate, CentreResponse, CentreUpdate
from app.schemas.centre_test import CentreTestCreate, CentreTestResponse
from app.services.centre_service import centre_service

router = APIRouter(prefix="/centres", tags=["Diagnostic Centres"])


@router.get(
    "",
    response_model=list[CentreResponse],
    status_code=status.HTTP_200_OK,
    summary="List diagnostic centres",
    description="Retrieve a paginated list of diagnostic centres with optional city and active status filters.",
)
def list_centres(
    city: str | None = Query(default=None, description="Filter by city name"),
    is_active: bool | None = Query(default=None, description="Filter by active status"),
    skip: int = Query(default=0, ge=0, description="Number of items to skip"),
    limit: int = Query(default=100, ge=1, le=100, description="Maximum number of items to return"),
    db: Session = Depends(get_db),
) -> Sequence[CentreResponse]:
    """Public endpoint to list diagnostic centres."""
    centres = centre_service.list_centres(
        db, city=city, is_active=is_active, skip=skip, limit=limit
    )
    return [CentreResponse.model_validate(c) for c in centres]


@router.get(
    "/{centre_id}",
    response_model=CentreResponse,
    status_code=status.HTTP_200_OK,
    summary="Get centre by ID",
    description="Retrieve detailed information for a specific diagnostic centre.",
)
def get_centre(
    centre_id: int = Path(..., ge=1, description="Diagnostic centre ID"),
    db: Session = Depends(get_db),
) -> CentreResponse:
    """Public endpoint to get a single diagnostic centre by ID."""
    centre = centre_service.get_centre(db, centre_id)
    return CentreResponse.model_validate(centre)


@router.post(
    "",
    response_model=CentreResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create diagnostic centre",
    description="Registers a new diagnostic centre location. Requires authentication.",
)
def create_centre(
    centre_in: CentreCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> CentreResponse:
    """Protected endpoint to create a new diagnostic centre."""
    centre = centre_service.create_centre(db, centre_in)
    return CentreResponse.model_validate(centre)


@router.patch(
    "/{centre_id}",
    response_model=CentreResponse,
    status_code=status.HTTP_200_OK,
    summary="Update diagnostic centre",
    description="Updates fields of an existing diagnostic centre. Requires authentication.",
)
def update_centre(
    centre_id: int = Path(..., ge=1, description="Diagnostic centre ID"),
    centre_in: CentreUpdate = ...,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> CentreResponse:
    """Protected endpoint to update a diagnostic centre."""
    centre = centre_service.update_centre(db, centre_id, centre_in)
    return CentreResponse.model_validate(centre)


@router.get(
    "/{centre_id}/tests",
    response_model=list[CentreTestResponse],
    status_code=status.HTTP_200_OK,
    summary="List tests at diagnostic centre",
    description="List all diagnostic tests offered by a centre along with their centre-specific pricing.",
)
def list_centre_tests(
    centre_id: int = Path(..., ge=1, description="Diagnostic centre ID"),
    is_available: bool | None = Query(default=None, description="Filter by availability"),
    db: Session = Depends(get_db),
) -> Sequence[CentreTestResponse]:
    """Public endpoint to list tests offered by a centre."""
    centre_tests = centre_service.list_centre_tests(db, centre_id, is_available=is_available)
    return [CentreTestResponse.model_validate(ct) for ct in centre_tests]


@router.post(
    "/{centre_id}/tests",
    response_model=CentreTestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Associate test with centre",
    description="Configures a test to be offered at a centre with a centre-specific price. Requires authentication.",
)
def add_centre_test(
    centre_id: int = Path(..., ge=1, description="Diagnostic centre ID"),
    centre_test_in: CentreTestCreate = ...,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> CentreTestResponse:
    """Protected endpoint to add a test and its price to a centre."""
    centre_test = centre_service.add_test_to_centre(db, centre_id, centre_test_in)
    return CentreTestResponse.model_validate(centre_test)
