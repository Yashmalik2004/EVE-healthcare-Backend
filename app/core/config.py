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

    # Redis & Rate Limiting
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str | None = None
    REDIS_URL: str | None = None
    RATE_LIMIT_ENABLED: bool = True

    @computed_field
    def EFFECTIVE_REDIS_URL(self) -> str:
        """Return the effective Redis connection URL.

        Priority:
        1. Explicit REDIS_URL (used in Docker / production)
        2. Assembled from REDIS_HOST, REDIS_PORT, REDIS_DB (local dev)
        """
        if self.REDIS_URL:
            return self.REDIS_URL
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"


    @computed_field
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        """Return the effective database URI.

        Priority:
        1. Explicit DATABASE_URL env var (used in Docker / production)
        2. Assembled from individual POSTGRES_* vars (local dev)
        """
        if self.DATABASE_URL:
            url = self.DATABASE_URL
            if url.startswith("postgres://"):
                return url.replace("postgres://", "postgresql+psycopg2://", 1)
            if url.startswith("postgresql://") and not url.startswith("postgresql+"):
                return url.replace("postgresql://", "postgresql+psycopg2://", 1)
            return url
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@"
            f"{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


settings = Settings()
