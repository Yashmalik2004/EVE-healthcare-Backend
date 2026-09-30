"""Redis-backed distributed rate limiting for the EVE Healthcare API.

Design & Architecture
---------------------
* Algorithm: Bucketed fixed-window counter backed by Redis.
* Distributed safety: Uses an atomic Redis Lua script (INCR + EXPIRE on first touch)
  to ensure all instances share counters without race conditions or orphaned keys.
* Identifier strategy:
  - IP-based (`ip:{client_ip}`) for unauthenticated / gateway endpoints (signup, login, webhook).
  - User-based (`user:{user_id}`) for authenticated endpoints (payments, bookings, profile).
* Fail-open: If Redis is temporarily unreachable or times out, the error is logged
  with full context, but the API continues processing requests (preserving patient care availability).
* Headers provided:
  - X-RateLimit-Limit: total requests allowed in the current window.
  - X-RateLimit-Remaining: requests remaining in the current window.
  - X-RateLimit-Reset: seconds until the current window resets.
  - Retry-After: seconds to wait when HTTP 429 Too Many Requests is returned.
"""

from collections.abc import Callable
import time
from typing import Any

from fastapi import Depends, Request, Response
import redis

from app.api.deps import get_current_active_user
from app.core.config import settings
from app.core.exceptions import RateLimitExceededException
from app.core.logging import logger
from app.models.user import User

# Atomic increment and expire script to prevent race conditions
_LUA_INCR_EXPIRE = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""


class InMemoryRedis:
    """In-memory Redis fake for fast, isolated unit and integration testing.

    Emulates the atomic Lua script and supports simulated time travel so tests
    never need to sleep or rely on an external Redis instance.
    """

    def __init__(self) -> None:
        self._data: dict[str, int] = {}
        self._expirations: dict[str, float] = {}
        self._time_offset: float = 0.0

    def time(self) -> float:
        """Return current simulated time."""
        return time.time() + self._time_offset

    def advance_time(self, seconds: float) -> None:
        """Advance simulated clock by a given number of seconds."""
        self._time_offset += seconds

    def eval(self, script: str, numkeys: int, key: str, expire: int) -> int:
        """Simulate the atomic increment and expire Lua script."""
        now = self.time()
        # Evict key if expired
        if key in self._expirations and now >= self._expirations[key]:
            self._data.pop(key, None)
            self._expirations.pop(key, None)

        val = self._data.get(key, 0) + 1
        self._data[key] = val
        if val == 1:
            self._expirations[key] = now + expire
        return val

    def ping(self) -> bool:
        """Health check probe."""
        return True

    def flushall(self) -> None:
        """Reset all in-memory keys and clock offset."""
        self._data.clear()
        self._expirations.clear()
        self._time_offset = 0.0


class RateLimiter:
    """Redis-backed rate limiter with fail-open fault tolerance."""

    def __init__(self, redis_client: Any | None = None) -> None:
        self._redis_client = redis_client

    def _get_client(self) -> Any:
        if self._redis_client is None:
            # Short timeouts prevent slow/down Redis from degrading API latency
            self._redis_client = redis.Redis.from_url(
                settings.EFFECTIVE_REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=1.0,
                socket_timeout=1.0,
            )
        return self._redis_client

    def _get_current_time(self, client: Any) -> float:
        """Get current timestamp, respecting test client's simulated clock if present.

        Real redis.Redis clients return a (seconds, microseconds) tuple from time().
        For real redis.Redis instances, use system time.time() to avoid an unnecessary
        network round-trip on every request and ensure fail-safe resilience.
        For test fakes and mocks, support both numeric returns and (seconds, microseconds) tuples.
        """
        if isinstance(client, redis.Redis):
            return time.time()

        if hasattr(client, "time") and callable(client.time):
            try:
                t = client.time()
                if isinstance(t, (tuple, list)):
                    return float(t[0]) + (float(t[1]) / 1_000_000.0 if len(t) > 1 else 0.0)
                return float(t)
            except Exception:
                return time.time()
        return time.time()

    def _execute_incr(self, client: Any, key: str, expire_seconds: int) -> int:
        """Execute atomic Lua script on the Redis client."""
        return int(client.eval(_LUA_INCR_EXPIRE, 1, key, expire_seconds))

    def check_rate_limit(
        self,
        identifier: str,
        limit: int,
        window_seconds: int,
        scope: str,
        request: Request,
        response: Response | None = None,
    ) -> None:
        """Enforce rate limit for a given identifier and scope.

        Raises:
            RateLimitExceededException (HTTP 429) if the limit is exceeded.
        """
        if not settings.RATE_LIMIT_ENABLED:
            return

        client = self._get_client()
        now = self._get_current_time(client)

        window_bucket = int(now // window_seconds)
        key = f"rate_limit:{scope}:{identifier}:{window_bucket}"
        expire_seconds = int(window_seconds * 2)

        # Seconds remaining until this window bucket rolls over
        next_window_start = (window_bucket + 1) * window_seconds
        retry_after = max(1, int(next_window_start - now))

        try:
            current = self._execute_incr(client, key, expire_seconds)
        except Exception as exc:
            # Fail-open behavior:
            # If Redis is unavailable, log the failure and allow the request so
            # healthcare services remain operational.
            logger.error(
                f"Redis rate limiter unavailable (failing open): "
                f"[{request.method} {request.url.path}] scope='{scope}' "
                f"identifier='{identifier}' error={type(exc).__name__}: {exc}"
            )
            return

        remaining = max(0, limit - current)

        # Store in request.state so the rate-limit-headers middleware can attach
        # these values to ANY response type, including exception responses where
        # the injected `Response` object's headers would otherwise be discarded.
        request.state.rate_limit = {
            "limit": limit,
            "remaining": remaining,
            "reset": retry_after,
        }

        # Populate standard headers on the outgoing response if provided
        if response is not None:
            response.headers["X-RateLimit-Limit"] = str(limit)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            response.headers["X-RateLimit-Reset"] = str(retry_after)

        if current > limit:
            id_type = identifier.split(":", 1)[0] if ":" in identifier else "unknown"
            logger.warning(
                f"Rate limit exceeded: [{request.method} {request.url.path}] "
                f"scope='{scope}' identifier_type='{id_type}' identifier='{identifier}' "
                f"limit={limit}/{window_seconds}s count={current} retry_after={retry_after}s"
            )
            raise RateLimitExceededException(
                message="Too many requests. Please try again later.",
                retry_after=retry_after,
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(retry_after),
                },
            )

    def reset(self) -> None:
        """Reset internal store if client supports it."""
        client = self._redis_client
        if client is not None and hasattr(client, "flushall"):
            client.flushall()


# Global default rate limiter singleton
_default_rate_limiter = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    """Return the active rate limiter instance."""
    return _default_rate_limiter


def set_rate_limiter(limiter: RateLimiter) -> None:
    """Set the active rate limiter instance (useful for test overrides)."""
    global _default_rate_limiter
    _default_rate_limiter = limiter


def get_client_ip(request: Request) -> str:
    """Extract client IP address from request.client without trusting spoofable headers.

    Note:
    We deliberately do not inspect client-supplied headers like X-Forwarded-For
    to prevent IP spoofing attacks, as our deployment does not configure a trusted
    reverse proxy header translation layer.
    """
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


def rate_limit_ip(
    requests: int, window: int = 60, scope: str = "default"
) -> Callable[[Request, Response], None]:
    """FastAPI dependency for IP-based rate limiting."""

    def dependency(request: Request, response: Response) -> None:
        limiter = get_rate_limiter()
        client_ip = get_client_ip(request)
        limiter.check_rate_limit(
            identifier=f"ip:{client_ip}",
            limit=requests,
            window_seconds=window,
            scope=scope,
            request=request,
            response=response,
        )

    return dependency


def rate_limit_user(
    requests: int, window: int = 60, scope: str = "default"
) -> Callable[[Request, Response, User], User]:
    """FastAPI dependency for authenticated user-based rate limiting."""

    def dependency(
        request: Request,
        response: Response,
        current_user: User = Depends(get_current_active_user),
    ) -> User:
        limiter = get_rate_limiter()
        limiter.check_rate_limit(
            identifier=f"user:{current_user.id}",
            limit=requests,
            window_seconds=window,
            scope=scope,
            request=request,
            response=response,
        )
        return current_user

    return dependency
