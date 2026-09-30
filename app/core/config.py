from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Application
    APP_NAME: str = "EVE Healthcare Diagnostic Service"
    APP_ENV: str = "development"
    DEBUG: bool = True
    API_V1_STR: str = "/api/v1"

    # Security — JWT placeholders (implementation deferred to auth phase)
    SECRET_KEY: str = "supersecretkeyforevediagnosticbackendengineeringassignment2026"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    ALGORITHM: str = "HS256"

    # Database — individual components for local compose / override via DATABASE_URL
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "eve_user"
    POSTGRES_PASSWORD: str = "eve_password"
    POSTGRES_DB: str = "eve_healthcare"
    DATABASE_URL: str | None = None

    # Test database — SQLite in-memory by default so tests never touch Postgres
    TEST_DATABASE_URL: str = "sqlite:///:memory:"

    # Logging
    LOG_LEVEL: str = "INFO"

    @computed_field
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        """Return the effective database URI.

        Priority:
        1. Explicit DATABASE_URL env var (used in Docker / production)
        2. Assembled from individual POSTGRES_* vars (local dev)
        """
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@"
            f"{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


settings = Settings()
