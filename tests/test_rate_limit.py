"""Automated test suite for Redis-backed API rate limiting.

Covers the 12 required test scenarios:
1. Request below the limit succeeds (with rate limit headers).
2. Requests at the limit succeed.
3. Request exceeding the limit returns HTTP 429 Too Many Requests.
4. Counter resets after the time window.
5. Different IP addresses have independent limits.
6. Different authenticated users have independent user-based limits.
7. Login uses the 5/min/IP limit.
8. Signup uses the 3/min/IP limit.
9. Payment uses the authenticated-user limit (10/min/user).
10. Webhook uses the IP-based limit (30/min/IP).
11. Health endpoint is not rate limited.
12. Redis failure fails open without disrupting normal API requests.
"""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
import pytest
import redis
from sqlalchemy.orm import Session

from app.core.exceptions import RateLimitExceededException
from app.core.rate_limit import InMemoryRedis, RateLimiter, get_rate_limiter, set_rate_limiter
from app.main import app
from app.models.appointment_slot import AppointmentSlot
from app.models.centre import DiagnosticCentre
from app.models.centre_test import CentreTest
from app.models.diagnostic_test import DiagnosticTest
from app.models.enums import BookingStatus
from app.models.user import User


def _create_test_client(ip: str = "127.0.0.1") -> TestClient:
    """Helper to instantiate a TestClient with a specific client IP address."""
    return TestClient(app, client=(ip, 50000))


def _register_and_login(
    client: TestClient, email: str, password: str = "Password123!"
) -> tuple[dict[str, str], int]:
    """Helper to register and login a user, returning auth headers and user ID."""
    reg = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": password, "full_name": "Rate Limit Test User"},
    )
    user_id = reg.json()["id"]
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    token = login_res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, user_id


# ── Scenario 1: Request below the limit succeeds ─────────────────────────────


def test_request_below_limit_succeeds(test_rate_limiter: RateLimiter):
    """A request below the limit succeeds and receives rate limit headers."""
    client = _create_test_client("10.0.0.1")
    res = client.post(
        "/api/v1/auth/login",
        json={"email": "nonexistent@example.com", "password": "WrongPassword1!"},
    )
    # Login fails credentials (401), but crucially was not rate-limited (not 429)
    assert res.status_code == 401
    assert res.headers.get("X-RateLimit-Limit") == "5"
    assert res.headers.get("X-RateLimit-Remaining") == "4"


# ── Scenario 2: Requests at the limit succeed ────────────────────────────────


def test_requests_at_limit_succeed(test_rate_limiter: RateLimiter):
    """Requests up to and including the exact limit succeed without triggering 429."""
    client = _create_test_client("10.0.0.2")
    for i in range(5):
        res = client.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "WrongPassword1!"},
        )
        assert res.status_code != 429
        expected_remaining = str(4 - i)
        assert res.headers.get("X-RateLimit-Remaining") == expected_remaining


# ── Scenario 3: Request exceeding the limit returns 429 ──────────────────────


def test_request_exceeding_limit_returns_429(test_rate_limiter: RateLimiter):
    """The (limit + 1)th request returns HTTP 429 with Retry-After and standard error envelope."""
    client = _create_test_client("10.0.0.3")
    for _ in range(5):
        client.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "WrongPassword1!"},
        )

    # 6th request exceeds limit
    res6 = client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "WrongPassword1!"},
    )
    assert res6.status_code == 429
    data = res6.json()
    assert data["success"] is False
    assert data["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert "Too many requests" in data["error"]["message"]
    assert "Retry-After" in res6.headers
    assert int(res6.headers["Retry-After"]) >= 1
    assert res6.headers.get("X-RateLimit-Remaining") == "0"


# ── Scenario 4: Counter resets after the time window ─────────────────────────


def test_counter_resets_after_time_window(test_rate_limiter: RateLimiter):
    """Advancing time beyond the rate limit window resets the counter."""
    in_memory: InMemoryRedis = test_rate_limiter._redis_client
    client = _create_test_client("10.0.0.4")

    # Exhaust 5 requests
    for _ in range(5):
        client.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "WrongPassword1!"},
        )
    assert client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "WrongPassword1!"},
    ).status_code == 429

    # Advance simulated time past the 60-second window
    in_memory.advance_time(61.0)

    # Quota is restored
    res_after = client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "WrongPassword1!"},
    )
    assert res_after.status_code != 429
    assert res_after.headers.get("X-RateLimit-Remaining") == "4"


# ── Scenario 5: Different IP addresses have independent limits ───────────────


def test_different_ip_addresses_have_independent_limits(test_rate_limiter: RateLimiter):
    """Rate limiting on IP A does not affect requests originating from IP B."""
    client_a = _create_test_client("192.168.1.10")
    client_b = _create_test_client("192.168.1.20")

    # Exhaust limit for IP A
    for _ in range(5):
        client_a.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "WrongPassword1!"},
        )
    assert client_a.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "WrongPassword1!"},
    ).status_code == 429

    # IP B is unaffected
    res_b = client_b.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "WrongPassword1!"},
    )
    assert res_b.status_code != 429
    assert res_b.headers.get("X-RateLimit-Remaining") == "4"


# ── Scenario 6: Different authenticated users have independent limits ────────


def test_different_authenticated_users_have_independent_limits(
    test_rate_limiter: RateLimiter, db: Session
):
    """User A's rate limit exhaustion does not block User B."""
    client = _create_test_client("10.0.0.6")

    # Set up User A & User B
    headers_a, id_a = _register_and_login(client, "user_a@example.com")
    headers_b, id_b = _register_and_login(client, "user_b@example.com")

    # Exhaust User A's /auth/me quota (60 requests)
    for _ in range(60):
        res = client.get("/api/v1/auth/me", headers=headers_a)
        assert res.status_code == 200

    # User A is now rate-limited
    res_a_blocked = client.get("/api/v1/auth/me", headers=headers_a)
    assert res_a_blocked.status_code == 429

    # User B can still access /auth/me normally
    res_b_ok = client.get("/api/v1/auth/me", headers=headers_b)
    assert res_b_ok.status_code == 200


# ── Scenario 7: Login uses 5/min/IP limit ────────────────────────────────────


def test_login_uses_5_per_minute_ip_limit(test_rate_limiter: RateLimiter):
    """POST /auth/login allows exactly 5 requests per minute per IP."""
    client = _create_test_client("10.0.0.7")
    for i in range(5):
        res = client.post(
            "/api/v1/auth/login",
            json={"email": f"attempt{i}@example.com", "password": "WrongPassword1!"},
        )
        assert res.status_code != 429

    # 6th request returns 429
    blocked = client.post(
        "/api/v1/auth/login",
        json={"email": "attempt6@example.com", "password": "WrongPassword1!"},
    )
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"


# ── Scenario 8: Signup uses 3/min/IP limit ───────────────────────────────────


def test_signup_uses_3_per_minute_ip_limit(test_rate_limiter: RateLimiter):
    """POST /auth/signup allows exactly 3 requests per minute per IP."""
    client = _create_test_client("10.0.0.8")
    for i in range(3):
        res = client.post(
            "/api/v1/auth/signup",
            json={
                "email": f"signup_{i}@example.com",
                "password": "Password123!",
                "full_name": f"User {i}",
            },
        )
        assert res.status_code == 201

    # 4th request returns 429
    blocked = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "signup_blocked@example.com",
            "password": "Password123!",
            "full_name": "Blocked User",
        },
    )
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"


# ── Scenario 9: Payment uses authenticated-user limit (10/min/user) ──────────


def test_payment_uses_authenticated_user_limit(
    test_rate_limiter: RateLimiter, db: Session
):
    """POST /payments allows exactly 10 requests per minute per authenticated user."""
    client = _create_test_client("10.0.0.9")
    headers, user_id = _register_and_login(client, "payer@example.com")

    # Send 10 payment requests (even if invalid booking_id, rate limit evaluates first)
    for _ in range(10):
        res = client.post(
            "/api/v1/payments",
            headers=headers,
            json={"booking_id": 9999, "amount": 500.0, "simulate_status": "SUCCESS"},
        )
        # Not rate limited (it will be 404 or validation error)
        assert res.status_code != 429

    # 11th request hits the 10/min user rate limit
    res_11 = client.post(
        "/api/v1/payments",
        headers=headers,
        json={"booking_id": 9999, "amount": 500.0, "simulate_status": "SUCCESS"},
    )
    assert res_11.status_code == 429
    assert res_11.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"


# ── Scenario 10: Webhook uses IP-based limit (30/min/IP) ─────────────────────


def test_webhook_uses_ip_based_limit(test_rate_limiter: RateLimiter):
    """POST /payments/webhook allows exactly 30 requests per minute per IP."""
    client = _create_test_client("10.0.0.10")
    for i in range(30):
        res = client.post(
            "/api/v1/payments/webhook",
            json={
                "event_id": f"evt-{i}",
                "event_type": "payment.success",
                "payment_id": f"PAY-{i}",
                "status": "SUCCESS",
            },
        )
        assert res.status_code != 429

    # 31st request triggers rate limit
    blocked = client.post(
        "/api/v1/payments/webhook",
        json={
            "event_id": "evt-31",
            "event_type": "payment.success",
            "payment_id": "PAY-31",
            "status": "SUCCESS",
        },
    )
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"


# ── Scenario 11: Health endpoint is not rate limited ─────────────────────────


def test_health_endpoint_not_rate_limited(test_rate_limiter: RateLimiter):
    """GET /health and GET /docs are not subject to rate limiting."""
    client = _create_test_client("10.0.0.11")
    # Send 50 requests in rapid succession
    for _ in range(50):
        res = client.get("/health")
        assert res.status_code == 200

    docs_res = client.get("/docs")
    assert docs_res.status_code == 200


# ── Scenario 12: Redis failure fails open ─────────────────────────────────────


def test_redis_failure_fails_open(test_rate_limiter: RateLimiter):
    """When Redis is unavailable or throws errors, the API continues processing requests (fail-open)."""
    # Create a mock client that raises Redis ConnectionError on eval
    failing_client = MagicMock()
    failing_client.eval.side_effect = redis.ConnectionError("Redis connection refused on port 6379")
    failing_client.time.return_value = 1000.0

    failing_limiter = RateLimiter(redis_client=failing_client)
    set_rate_limiter(failing_limiter)

    client = _create_test_client("10.0.0.12")

    # Send multiple requests — none should fail with 500 or 429
    for _ in range(10):
        res = client.post(
            "/api/v1/auth/login",
            json={"email": "anyone@example.com", "password": "WrongPassword1!"},
        )
        assert res.status_code == 401  # Normal credential failure, not 500 or 429

    # Restore the default test rate limiter
    set_rate_limiter(test_rate_limiter)
