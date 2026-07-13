"""Signup / login / current-user / password + user management endpoints."""
import logging
import secrets
import time
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import VALID_ROLES, create_token, hash_password, require_admin, require_user, verify_password
from backend.config import ENVIRONMENT, settings
from backend.database import get_db
from backend.models import User
from backend.routers import audit
from backend.schemas import (
    ForgotPasswordRequest, LoginRequest, SignupRequest, TokenResponse, UserOut,
)
from backend.services import dual_control, emailer, ldap_auth

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger(__name__)

MIN_PASSWORD_LEN = 8


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


# Simple in-memory login throttle (per client IP). Single-node; for multi-node
# deployments move this to a shared store (e.g. Redis).
_LOGIN_ATTEMPTS: dict[str, list[float]] = defaultdict(list)
_MAX_ATTEMPTS = 10
_WINDOW_SECONDS = 300  # 5 minutes


def _rate_limited(key: str) -> bool:
    now = time.time()
    _LOGIN_ATTEMPTS[key] = [t for t in _LOGIN_ATTEMPTS[key] if now - t < _WINDOW_SECONDS]
    return len(_LOGIN_ATTEMPTS[key]) >= _MAX_ATTEMPTS


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _valid_email(email: str) -> bool:
    return "@" in email and "." in email.split("@")[-1]


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def signup(body: SignupRequest, request: Request, db: AsyncSession = Depends(get_db)):
    email = _normalize_email(body.email)
    if not _valid_email(email):
        raise HTTPException(status_code=400, detail="A valid email address is required")
    if len(body.password) < MIN_PASSWORD_LEN:
        raise HTTPException(status_code=400, detail=f"Password must be at least {MIN_PASSWORD_LEN} characters")

    exists = (await db.execute(
        select(User).where((User.email == email) | (User.username == email))
    )).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="An account with that email already exists")

    # First user to register becomes admin, but production bootstrap must be
    # intentional. After bootstrap, public signup is off unless explicitly enabled.
    is_first = (await db.execute(select(func.count()).select_from(User))).scalar_one() == 0
    if is_first:
        if ENVIRONMENT.lower() != "development":
            if not settings.setup_token or body.setup_token != settings.setup_token:
                raise HTTPException(status_code=403, detail="Setup token required for first admin")
    elif not settings.allow_signup:
        raise HTTPException(status_code=403, detail="Signup is disabled. Ask an admin to create your account.")

    user = User(
        username=email,            # username mirrors email; login is by email
        email=email,
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
    from backend.auth import client_ip
    ip = client_ip(request) or "unknown"
    if _rate_limited(ip):
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again in a few minutes.")

    email = _normalize_email(body.email)
    # Match on email, falling back to username so pre-email accounts can still sign in.
    user = (await db.execute(
        select(User).where((User.email == email) | (User.username == email))
    )).scalar_one_or_none()

    # 1) Local password auth (always tried first, so the built-in admin keeps
    #    working even if the directory is down or misconfigured).
    if user and verify_password(body.password, user.password_hash):
        auth_via = "local"
    # 2) Directory (LDAP/AD) auth, if enabled — verifies against AD and
    #    auto-provisions/updates the local user record.
    elif ldap_auth.is_enabled():
        import asyncio
        raw_id = body.email.strip()
        try:
            info = await asyncio.get_running_loop().run_in_executor(
                None, ldap_auth.authenticate, raw_id, body.password)
        except RuntimeError as e:
            log.error(f"Directory auth error for {raw_id!r}: {e}")
            info = None
        if not info:
            _LOGIN_ATTEMPTS[ip].append(time.time())
            log.warning(f"Failed directory login for {raw_id!r}")
            await audit.record(raw_id, "LOGIN_FAILED", detail="directory", request=request)
            raise HTTPException(status_code=401, detail="Invalid email or password")
        user = await _upsert_directory_user(db, info)
        auth_via = "directory"
    else:
        _LOGIN_ATTEMPTS[ip].append(time.time())
        log.warning(f"Failed login attempt for email={email!r}")
        await audit.record(email, "LOGIN_FAILED", request=request)
        raise HTTPException(status_code=401, detail="Invalid email or password")

    _LOGIN_ATTEMPTS.pop(ip, None)  # clear on success
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")

    user.last_login_at = datetime.utcnow()
    await db.commit()
    await db.refresh(user)

    await audit.record(user.username, "LOGIN", detail=auth_via if auth_via != "local" else None, request=request)
    return TokenResponse(token=create_token(user), user=UserOut.model_validate(user))


async def _upsert_directory_user(db: AsyncSession, info: dict) -> User:
    """Create or update the local record for a directory-authenticated user.
    Directory users have no usable local password (they authenticate via AD)."""
    username = info["username"]
    user = (await db.execute(
        select(User).where((User.username == username) | (User.email == (info.get("email") or "\0")))
    )).scalar_one_or_none()
    if user:
        # Keep role/attributes in sync with the directory on each login.
        user.role = info["role"]
        if info.get("email"):
            user.email = info["email"]
        if info.get("full_name"):
            user.full_name = info["full_name"]
    else:
        user = User(
            username=username, email=info.get("email"), full_name=info.get("full_name"),
            password_hash=hash_password(secrets.token_urlsafe(32)),  # unusable locally
            role=info["role"], last_login_at=datetime.utcnow(),
        )
        db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(require_user)):
    return UserOut.model_validate(user)


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if len(body.new_password) < MIN_PASSWORD_LEN:
        raise HTTPException(status_code=400, detail=f"Password must be at least {MIN_PASSWORD_LEN} characters")
    user.password_hash = hash_password(body.new_password)
    await db.commit()
    await audit.record(user.username, "PASSWORD_CHANGED", request=request)
    return {"changed": True}


# ─── Admin user management ────────────────────────────────────────────────────
# Sensitive changes go through dual control (maker-checker): with two or more
# active admins, the requesting admin's change is queued and a *different*
# admin must approve it. See backend/services/dual_control.py.

@router.get("/users", response_model=list[UserOut])
async def list_users(db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)):
    users = (await db.execute(select(User).order_by(User.created_at))).scalars().all()
    return [UserOut.model_validate(u) for u in users]


async def _get_target(db: AsyncSession, user_id: str) -> User:
    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    return target


async def _guard_not_last_admin(db: AsyncSession, target: User, change: str) -> None:
    """Block changes that would leave the system with no active admin."""
    if target.role == "admin" and target.is_active:
        others = (await db.execute(
            select(func.count()).select_from(User).where(
                User.role == "admin", User.is_active == True, User.id != target.id)  # noqa: E712
        )).scalar_one()
        if others == 0:
            raise HTTPException(status_code=400, detail=f"Cannot {change} the last active admin")


async def _issue_temp_password(db: AsyncSession, target: User) -> tuple[str, bool]:
    """Set a fresh temporary password; email it when possible. Returns (temp, emailed)."""
    temp_password = secrets.token_urlsafe(9)
    target.password_hash = hash_password(temp_password)
    await db.commit()
    emailed = False
    if target.email and emailer.is_configured():
        emailed = emailer.send_password_email(
            target.email, target.full_name or target.username, temp_password, by_admin=True
        )
    return temp_password, emailed


# ── Executors: apply the change, either immediately (single-admin mode) or at
#    approval time by a second admin. They re-validate state at execution time.

@dual_control.register("USER_CREATE")
async def _exec_create_user(db: AsyncSession, payload: dict, actor: str, request: Request | None) -> dict:
    email = _normalize_email(payload["email"])
    role = payload["role"]
    exists = (await db.execute(
        select(User).where((User.email == email) | (User.username == email))
    )).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="An account with that email already exists")

    user = User(
        username=email,
        email=email,
        full_name=(payload.get("full_name") or "").strip() or None,
        password_hash=hash_password(secrets.token_urlsafe(32)),  # replaced just below
        role=role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    temp_password, emailed = await _issue_temp_password(db, user)

    await audit.record(actor, "USER_CREATED", target=user.username,
                       detail=f"role={role}; {'temp password emailed' if emailed else 'temp password shown on-screen'}",
                       request=request)
    return {
        "username": user.username, "email": user.email, "role": user.role, "emailed": emailed,
        # Only surfaced when we couldn't email it.
        "temp_password": None if emailed else temp_password,
    }


@dual_control.register("USER_SET_ROLE")
async def _exec_set_role(db: AsyncSession, payload: dict, actor: str, request: Request | None) -> dict:
    target = await _get_target(db, payload["user_id"])
    role = payload["role"]
    if role != "admin":
        await _guard_not_last_admin(db, target, "remove the admin role of")
    target.role = role
    await db.commit()
    await audit.record(actor, "USER_ROLE_CHANGED", target=target.username, detail=role, request=request)
    return {"username": target.username, "role": target.role}


@dual_control.register("USER_TOGGLE_ACTIVE")
async def _exec_toggle_active(db: AsyncSession, payload: dict, actor: str, request: Request | None) -> dict:
    target = await _get_target(db, payload["user_id"])
    if target.is_active:
        await _guard_not_last_admin(db, target, "disable")
    target.is_active = not target.is_active
    await db.commit()
    action = "USER_ENABLED" if target.is_active else "USER_DISABLED"
    await audit.record(actor, action, target=target.username, request=request)
    return {"username": target.username, "is_active": target.is_active}


@dual_control.register("USER_RESET_PASSWORD")
async def _exec_reset_password(db: AsyncSession, payload: dict, actor: str, request: Request | None) -> dict:
    target = await _get_target(db, payload["user_id"])
    temp_password, emailed = await _issue_temp_password(db, target)
    await audit.record(actor, "USER_PASSWORD_RESET", target=target.username,
                       detail="emailed" if emailed else "shown on-screen", request=request)
    return {
        "username": target.username, "email": target.email, "emailed": emailed,
        "temp_password": None if emailed else temp_password,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

class CreateUserRequest(BaseModel):
    email: str
    full_name: str | None = None
    role: str = "analyst"


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    body: CreateUserRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Admin-created account (the only way to add users while signup is off).
    A temporary password is emailed to the user, or shown once if SMTP isn't set."""
    email = _normalize_email(body.email)
    if not _valid_email(email):
        raise HTTPException(status_code=400, detail="A valid email address is required")
    role = body.role.strip().lower()
    if role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Role must be one of: {', '.join(sorted(VALID_ROLES))}")
    exists = (await db.execute(
        select(User).where((User.email == email) | (User.username == email))
    )).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="An account with that email already exists")

    return await dual_control.submit_or_execute(
        db, request, admin,
        action="USER_CREATE",
        payload={"email": email, "full_name": body.full_name, "role": role},
        summary=f"Create {role} account for {email}",
        target=email,
    )


@router.post("/users/{user_id}/reset-password")
async def reset_password(
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    target = await _get_target(db, user_id)
    # Resetting an ADMIN's password is an account-takeover vector (the temp
    # password may be shown on-screen), so it requires a second admin's approval.
    # Non-admin resets stay immediate: they're the everyday recovery path.
    if target.role == "admin":
        return await dual_control.submit_or_execute(
            db, request, admin,
            action="USER_RESET_PASSWORD",
            payload={"user_id": user_id},
            summary=f"Reset password of admin {target.username}",
            target=target.username,
        )
    return await _exec_reset_password(db, {"user_id": user_id}, admin.username, request)


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Self-service reset. Always returns the same generic response so it can't be
    used to probe which emails have accounts."""
    email = _normalize_email(body.email)
    generic = {
        "message": "If an account exists for that email, a temporary password has been sent.",
        "email_configured": emailer.is_configured(),
    }
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user and user.is_active and emailer.is_configured():
        temp_password = secrets.token_urlsafe(9)
        user.password_hash = hash_password(temp_password)
        await db.commit()
        emailer.send_password_email(user.email, user.full_name or user.username, temp_password, by_admin=False)
        await audit.record(user.username, "PASSWORD_RESET_REQUESTED", request=request)
    else:
        # Log the attempt without confirming existence to the caller.
        log.info(f"Forgot-password request for email={email!r} (delivered={bool(user and emailer.is_configured())})")
    return generic


class RoleUpdate(BaseModel):
    role: str


@router.post("/users/{user_id}/role")
async def set_role(
    user_id: str,
    body: RoleUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    role = body.role.strip().lower()
    if role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Role must be one of: {', '.join(sorted(VALID_ROLES))}")
    target = await _get_target(db, user_id)
    if role != "admin":
        # Fast feedback at request time; the executor re-checks at approval time.
        await _guard_not_last_admin(db, target, "remove the admin role of")
    return await dual_control.submit_or_execute(
        db, request, admin,
        action="USER_SET_ROLE",
        payload={"user_id": user_id, "role": role},
        summary=f"Change role of {target.username} from {target.role} to {role}",
        target=target.username,
    )


@router.post("/users/{user_id}/toggle-active")
async def toggle_active(
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    target = await _get_target(db, user_id)
    if target.is_active:
        await _guard_not_last_admin(db, target, "disable")
    return await dual_control.submit_or_execute(
        db, request, admin,
        action="USER_TOGGLE_ACTIVE",
        payload={"user_id": user_id},
        summary=f"{'Disable' if target.is_active else 'Enable'} account {target.username}",
        target=target.username,
    )
