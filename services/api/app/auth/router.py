"""Public authentication endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.dependencies import get_current_user
from app.core.security import (
    create_access_token,
    hash_password,
    normalize_email,
    verify_password,
)
from app.db.models.credits import CreditBalance
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.user import TokenResponse, UserLogin, UserRegister, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register_user(payload: UserRegister, db: Session = Depends(get_db)) -> User:
    normalized_email = normalize_email(payload.email)
    display_name = payload.display_name.strip() if payload.display_name else None
    if display_name == "":
        display_name = None

    if db.query(User).filter(User.email == normalized_email).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    settings = get_settings()
    owner_email = (
        normalize_email(settings.nestai_owner_email)
        if settings.nestai_owner_email and settings.nestai_owner_email.strip()
        else None
    )

    user = User(
        email=normalized_email,
        hashed_password=hash_password(payload.password),
        display_name=display_name,
        is_active=True,
        is_admin=owner_email == normalized_email,
        tier="free",
        plan="FREE",
    )
    db.add(user)

    try:
        db.flush()
        db.add(
            CreditBalance(
                user_id=user.id,
                tier=user.tier,
            )
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        ) from exc

    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login_user(payload: UserLogin, db: Session = Depends(get_db)) -> TokenResponse:
    normalized_email = normalize_email(payload.email)
    user = db.query(User).filter(User.email == normalized_email).first()
    if not user or not verify_password(payload.password, user.password_hash) or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(subject=str(user.id))
    return TokenResponse(access_token=access_token, token_type="bearer")


@router.get("/me", response_model=UserResponse)
def read_current_user(current_user: User = Depends(get_current_user)) -> User:
    return current_user
