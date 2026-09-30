"""Health check schema."""

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Schema for service health check response."""

    status: str = Field(..., description="Overall health status: 'healthy' or 'degraded'")
    app_name: str = Field(..., description="Application name")
    environment: str = Field(..., description="Deployment environment")
    database: str = Field(..., description="Database connectivity status: 'healthy' or 'unhealthy'")
    version: str = Field("1.0.0", description="Service semantic version")
    api_version: str = Field("/api/v1", description="Current API route prefix")
    timestamp: str = Field(..., description="ISO 8601 UTC timestamp of check")
