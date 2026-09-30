"""User data access layer.

All database queries for the User model live here.  Services call these
methods and never build raw SQLAlchemy queries themselves, keeping query
logic centralised and testable in isolation.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.enums import UserRole


class UserRepository:
    """Static-method repository for User persistence operations."""

    @staticmethod
    def get_by_id(db: Session, user_id: int) -> User | None:
        """Return the User with the given PK, or None if not found."""
        return db.scalar(select(User).where(User.id == user_id))

    @staticmethod
    def get_by_email(db: Session, email: str) -> User | None:
        """Return the User with the given email (case-insensitive), or None."""
        return db.scalar(
            select(User).where(User.email == email.lower().strip())
        )

    @staticmethod
    def create(
        db: Session,
        *,
        email: str,
        password_hash: str,
        full_name: str,
        role: UserRole = UserRole.PATIENT,
    ) -> User:
        """Persist a new User row and return the refreshed instance.

        Args:
            db:            Database session.
            email:         Normalised (lowercase, stripped) email address.
            password_hash: Argon2id hash of the plaintext password.
            full_name:     User's display name.
            role:          Account role — defaults to PATIENT for public signups.

        Returns:
            The newly created User ORM instance (PK populated).
        """
        user = User(
            email=email.lower().strip(),
            password_hash=password_hash,
            full_name=full_name.strip(),
            role=role,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
