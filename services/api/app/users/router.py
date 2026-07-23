"""
app/users/router.py — Authenticated user self-service endpoints.

Routes:
    GET   /users/me          Return current user's full profile
    PATCH /users/me          Update display name or other patchable fields
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.router import _user_response
from app.auth.schemas import UpdateProfileRequest, UserResponse
from app.db.models.user import User
from app.db.session import get_db

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Return the authenticated user's full profile."""
    return _user_response(current_user, db)


@router.patch("/me", response_model=UserResponse)
def update_me(
    body: UpdateProfileRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Update mutable profile fields (display name)."""
    if body.display_name is not None:
        current_user.display_name = body.display_name or None
    db.commit()
    db.refresh(current_user)
    return _user_response(current_user, db)
