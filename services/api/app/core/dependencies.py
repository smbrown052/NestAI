"""Shared FastAPI auth dependencies."""

from fastapi import Depends, HTTPException, status
from app.auth.dependencies import get_current_user
from app.db.models.user import User


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user
