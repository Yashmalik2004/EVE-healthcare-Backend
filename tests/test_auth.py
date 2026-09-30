"""Authentication and Authorization test suite — Phase 3.

Covers:
- POST /api/v1/auth/signup (success, duplicate email, invalid email, short password, privilege escalation prevention)
- POST /api/v1/auth/login (success, case-insensitivity, bad password, non-existent user, inactive account)
- GET /api/v1/auth/me (valid token, missing token, invalid/corrupt token, expired token, inactive account)
- Role-based access control dependency (require_role)
"""

from datetime import timedelta

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.core.security import create_access_token
from app.main import app
from app.models.enums import UserRole
from app.models.user import User


# ── Signup Tests ──────────────────────────────────────────────────────────────


def test_signup_success(client: TestClient):
    """Registering a new valid user succeeds with 201 Created and PATIENT role."""
    payload = {
        "email": "alice@example.com",
        "password": "SecurePassword123!",
        "full_name": "Alice Smith",
    }
    response = client.post("/api/v1/auth/signup", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert data["email"] == "alice@example.com"
    assert data["full_name"] == "Alice Smith"
    assert data["role"] == "PATIENT"
    assert data["is_active"] is True
    assert "id" in data
    # Sensitive fields must never be returned
    assert "password" not in data
    assert "password_hash" not in data


def test_signup_duplicate_email(client: TestClient):
    """Registering with an already registered email returns 409 Conflict."""
    payload = {
        "email": "duplicate@example.com",
        "password": "SecurePassword123!",
        "full_name": "Duplicate User",
    }
    res1 = client.post("/api/v1/auth/signup", json=payload)
    assert res1.status_code == 201

    res2 = client.post("/api/v1/auth/signup", json=payload)
    assert res2.status_code == 409
    data = res2.json()
    assert data["success"] is False
    assert data["error"]["code"] == "DUPLICATE_USER"


def test_signup_invalid_email_format(client: TestClient):
    """Submitting an invalid email format returns 422 Unprocessable Entity."""
    payload = {
        "email": "not-a-valid-email",
        "password": "SecurePassword123!",
        "full_name": "Invalid Email",
    }
    response = client.post("/api/v1/auth/signup", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "VALIDATION_ERROR"


def test_signup_short_password(client: TestClient):
    """Submitting a password shorter than 8 characters returns 422."""
    payload = {
        "email": "shortpw@example.com",
        "password": "short",
        "full_name": "Short Password User",
    }
    response = client.post("/api/v1/auth/signup", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "VALIDATION_ERROR"


def test_signup_missing_required_fields(client: TestClient):
    """Omitting required fields returns 422."""
    response = client.post("/api/v1/auth/signup", json={"email": "missing@example.com"})
    assert response.status_code == 422
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "VALIDATION_ERROR"


def test_signup_role_privilege_escalation_attempt(client: TestClient):
    """Supplying role='ADMIN' during signup is overridden to PATIENT."""
    payload = {
        "email": "hacker@example.com",
        "password": "SecurePassword123!",
        "full_name": "Hacker Attempt",
        "role": "ADMIN",
    }
    response = client.post("/api/v1/auth/signup", json=payload)
    assert response.status_code == 201
    data = response.json()
    # Must be forced to PATIENT
    assert data["role"] == "PATIENT"


def test_signup_normalizes_email(client: TestClient):
    """Email is trimmed and converted to lowercase during signup."""
    payload = {
        "email": "  TrimMe@Example.COM  ",
        "password": "SecurePassword123!",
        "full_name": "Trimmed User",
    }
    response = client.post("/api/v1/auth/signup", json=payload)
    assert response.status_code == 201
    assert response.json()["email"] == "trimme@example.com"


# ── Login Tests ───────────────────────────────────────────────────────────────


def test_login_success(client: TestClient):
    """Valid credentials return 200 OK with JWT token and user info."""
    signup_payload = {
        "email": "bob@example.com",
        "password": "BobPassword123!",
        "full_name": "Bob Jones",
    }
    client.post("/api/v1/auth/signup", json=signup_payload)

    login_payload = {
        "email": "bob@example.com",
        "password": "BobPassword123!",
    }
    response = client.post("/api/v1/auth/login", json=login_payload)
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "bob@example.com"
    assert data["user"]["full_name"] == "Bob Jones"
    assert "password_hash" not in data["user"]


def test_login_case_insensitive_email(client: TestClient):
    """Login succeeds even when email casing or surrounding whitespace differs."""
    client.post(
        "/api/v1/auth/signup",
        json={
            "email": "casing@example.com",
            "password": "Password123!",
            "full_name": "Casing Test",
        },
    )

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "  CASING@EXAMPLE.COM ", "password": "Password123!"},
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


def test_login_invalid_password(client: TestClient):
    """Incorrect password returns 401 Unauthorized with INVALID_CREDENTIALS."""
    client.post(
        "/api/v1/auth/signup",
        json={
            "email": "wrongpass@example.com",
            "password": "CorrectPassword123!",
            "full_name": "Wrong Pass User",
        },
    )

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "wrongpass@example.com", "password": "WrongPassword999!"},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "INVALID_CREDENTIALS"


def test_login_nonexistent_user(client: TestClient):
    """Unregistered email returns 401 Unauthorized with INVALID_CREDENTIALS."""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "ghost@example.com", "password": "GhostPassword123!"},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "INVALID_CREDENTIALS"


def test_login_inactive_user(client: TestClient, db: Session):
    """Inactive accounts are rejected upon login."""
    res = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "inactive@example.com",
            "password": "Password123!",
            "full_name": "Inactive User",
        },
    )
    user_id = res.json()["id"]

    # Deactivate the account in the database
    user = db.get(User, user_id)
    assert user is not None
    user.is_active = False
    db.commit()

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "inactive@example.com", "password": "Password123!"},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "INVALID_CREDENTIALS"


# ── /auth/me Tests ────────────────────────────────────────────────────────────


def test_me_endpoint_authenticated(client: TestClient):
    """Calling /auth/me with valid Bearer token returns current user profile."""
    client.post(
        "/api/v1/auth/signup",
        json={
            "email": "profile@example.com",
            "password": "Password123!",
            "full_name": "Profile User",
        },
    )
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": "profile@example.com", "password": "Password123!"},
    )
    token = login_res.json()["access_token"]

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "profile@example.com"
    assert data["full_name"] == "Profile User"
    assert "password_hash" not in data


def test_me_endpoint_unauthorized_missing_token(client: TestClient):
    """Calling /auth/me without Authorization header returns 401."""
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "INVALID_TOKEN"


def test_me_endpoint_invalid_token(client: TestClient):
    """Calling /auth/me with malformed token returns 401."""
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer bad.malformed.token"},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "INVALID_TOKEN"


def test_me_endpoint_expired_token(client: TestClient):
    """Calling /auth/me with an expired JWT returns 401 with TOKEN_EXPIRED."""
    res = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "expired@example.com",
            "password": "Password123!",
            "full_name": "Expired User",
        },
    )
    user_id = res.json()["id"]

    expired_token = create_access_token(
        {"sub": str(user_id), "email": "expired@example.com", "role": "PATIENT"},
        expires_delta=timedelta(minutes=-15),
    )

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "TOKEN_EXPIRED"


def test_me_endpoint_inactive_user(client: TestClient, db: Session):
    """Calling /auth/me with a token belonging to an inactive user returns 403 Forbidden."""
    res = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "deactivated@example.com",
            "password": "Password123!",
            "full_name": "Deactivated User",
        },
    )
    user_id = res.json()["id"]

    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": "deactivated@example.com", "password": "Password123!"},
    )
    token = login_res.json()["access_token"]

    # Deactivate the user
    user = db.get(User, user_id)
    assert user is not None
    user.is_active = False
    db.commit()

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "FORBIDDEN"


def test_me_endpoint_token_user_not_found(client: TestClient):
    """A valid token referencing a non-existent user returns 401 INVALID_TOKEN."""
    token = create_access_token(
        {"sub": "999999", "email": "ghost@example.com", "role": "PATIENT"}
    )
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "INVALID_TOKEN"


def test_me_endpoint_token_missing_sub(client: TestClient):
    """A valid token missing the 'sub' subject claim returns 401 INVALID_TOKEN."""
    token = create_access_token({"email": "nosub@example.com", "role": "PATIENT"})
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "INVALID_TOKEN"


# ── RBAC require_role Dependency Tests ─────────────────────────────────────────


def test_require_role_access_control(client: TestClient, db: Session):
    """Test require_role dependency: ADMIN role allowed, PATIENT role rejected with 403."""

    # Define a temporary route protected with require_role(UserRole.ADMIN)
    @app.get("/test-admin-only", tags=["Testing"])
    def admin_only_endpoint(current_user: User = Depends(require_role(UserRole.ADMIN))):
        return {"message": f"Hello admin {current_user.email}"}

    # 1. Test with PATIENT user -> 403
    client.post(
        "/api/v1/auth/signup",
        json={
            "email": "patient_rbac@example.com",
            "password": "Password123!",
            "full_name": "Patient User",
        },
    )
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": "patient_rbac@example.com", "password": "Password123!"},
    )
    patient_token = login_res.json()["access_token"]

    patient_res = client.get(
        "/test-admin-only",
        headers={"Authorization": f"Bearer {patient_token}"},
    )
    assert patient_res.status_code == 403
    assert patient_res.json()["error"]["code"] == "FORBIDDEN"

    # 2. Elevate user to ADMIN in DB and test -> 200
    user = db.query(User).filter_by(email="patient_rbac@example.com").first()
    assert user is not None
    user.role = UserRole.ADMIN
    db.commit()

    admin_login = client.post(
        "/api/v1/auth/login",
        json={"email": "patient_rbac@example.com", "password": "Password123!"},
    )
    admin_token = admin_login.json()["access_token"]

    admin_res = client.get(
        "/test-admin-only",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert admin_res.status_code == 200
    assert "Hello admin" in admin_res.json()["message"]
