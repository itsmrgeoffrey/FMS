"""Signup / login / current-user endpoints."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import create_token, hash_password, require_user, verify_password
from backend.database import get_db
from backend.models import User
from backend.routers import audit
from backend.schemas import LoginRequest, SignupRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

MIN_PASSWORD_LEN = 8


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def signup(body: SignupRequest, request: Request, db: AsyncSession = Depends(get_db)):
    username = body.username.strip().lower()
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")
    if len(body.password) < MIN_PASSWORD_LEN:
        raise HTTPException(status_code=400, detail=f"Password must be at least {MIN_PASSWORD_LEN} characters")

    exists = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="Username already taken")

    # First user to register becomes admin.
    is_first = (await db.execute(select(func.count()).select_from(User))).scalar_one() == 0

    user = User(
        username=username,
        full_name=(body.full_name or "").strip() or None,
        password_hash=hash_password(body.password),
        role="admin" if is_first else "analyst",
        last_login_at=datetime.utcnow(),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    await audit.record(user.username, "SIGNUP", detail=f"role={user.role}", request=request)
    return TokenResponse(token=create_token(user), user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    username = body.username.strip().lower()
    user = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        # Do not reveal whether the username exists.
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")

    user.last_login_at = datetime.utcnow()
    await db.commit()
    await db.refresh(user)

    await audit.record(user.username, "LOGIN", request=request)
    return TokenResponse(token=create_token(user), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(require_user)):
    return UserOut.model_validate(user)
