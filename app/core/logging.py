"""Structured logging configuration for EVE Healthcare Backend."""

import logging
import sys

from app.core.config import settings

# Keys whose presence in a log message indicates potential sensitive data
SENSITIVE_KEYS: set[str] = {
    "password",
    "secret",
    "token",
    "authorization",
    "secret_key",
    "password_hash",
    "access_token",
}


class SensitiveFilter(logging.Filter):
    """Filter that suppresses log records containing sensitive key-value pairs."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            lower_msg = record.msg.lower()
            for key in SENSITIVE_KEYS:
                if key in lower_msg and ("=" in record.msg or ":" in record.msg):
                    # Log the fact that a sensitive record was suppressed, not the content
                    record.msg = "[REDACTED — sensitive data omitted from log]"
                    record.args = ()
                    break
        return True


def setup_logging() -> logging.Logger:
    """Configure and return the application logger.

    Uses structured format: timestamp | level | [logger_name] message
    Respects LOG_LEVEL from settings so it can be overridden per environment.
    """
    logger = logging.getLogger("eve_healthcare")
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logger.setLevel(log_level)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(log_level)
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        handler.addFilter(SensitiveFilter())
        logger.addHandler(handler)

    return logger


# Module-level logger instance — import and use throughout the application
logger = setup_logging()
