"""Cryptographic utilities — password hashing and JWT management.

Design decisions
----------------
* Argon2id is used for password hashing (OWASP-recommended, memory-hard).
* JWTs are signed with HS256 and contain only non-sensitive identifiers.
* ``decode_access_token`` raises native PyJWT exceptions so the caller
  (``get_current_user`` dependency) can map them to structured HTTP errors.
* Real secrets must NEVER be hard-coded — they are loaded from ``settings``.
"""

from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import settings

# Argon2id hasher with OWASP-recommended defaults.
# Memory: 64 MB, Iterations: 3, Parallelism: 1 — adjust per deployment.
_ph = PasswordHasher()


# ── Password Hashing ──────────────────────────────────────────────────────────


def get_password_hash(password: str) -> str:
    """Return an Argon2id hash of the plaintext password.

    The hash includes the salt and parameters — it is self-contained and
    safe to store in the database as-is.
    """
    return _ph.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Return True if ``plain_password`` matches the stored Argon2id hash.

    Returns False (never raises) on mismatch or corrupted hash so callers
    can treat both as an authentication failure without leaking detail.
    """
    try:
        return _ph.verify(hashed_password, plain_password)
    except (VerifyMismatchError, InvalidHashError):
        return False


# ── JWT ───────────────────────────────────────────────────────────────────────


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Create a signed JWT access token.

    The payload is extended with ``iat`` (issued-at) and ``exp`` (expiry)
    claims.  Callers supply the base claims; this function adds timing claims
    so the final token is complete and self-verifiable.

    Args:
        data:          Claims to include (e.g. ``{"sub": "1", "role": "PATIENT"}``).
        expires_delta: Custom expiry window; defaults to settings value.

    Returns:
        Encoded JWT string.
    """
    to_encode = data.copy()
    now = datetime.now(UTC)
    expire = now + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"iat": now, "exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT access token.

    Raises:
        jwt.ExpiredSignatureError: Token has passed its ``exp`` claim.
        jwt.PyJWTError:            Any other validation failure (bad sig, etc.).
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
