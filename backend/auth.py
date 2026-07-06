"""Authentication and authorization.

Two mechanisms:
- **User login** (browser): username/password -> a signed bearer token. Passwords
  are stored as PBKDF2-SHA256 hashes; tokens are HMAC-signed (stdlib, no external
  JWT dependency) and carry the user id/name/role plus an expiry.
- **API key** (machine-to-machine, e.g. the transaction ingestion endpoint): the
  optional shared FMS_API_KEY header.

Local dev uses the built-in users table. AD/LDAP/SSO can later be added as an
alternate provider behind the same login endpoint without touching callers.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import get_db
from backend.models import User

# ─── Password hashing (PBKDF2-SHA256, stdlib) ────────────────────────────────

_PBKDF2_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


# ─── Signed tokens (HMAC-SHA256, stdlib — JWT-equivalent) ────────────────────

def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64u_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def create_token(user: User) -> str:
    payload = {
        "uid": user.id,
        "username": user.username,
        "role": user.role,
        "exp": int(time.time()) + settings.auth_token_ttl_hours * 3600,
    }
    body = _b64u(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(settings.auth_secret.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64u(sig)}"


def _verify_token(token: str) -> dict | None:
    try:
        body, sig = token.split(".")
        expected = hmac.new(settings.auth_secret.encode(), body.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64u_decode(sig), expected):
            return None
        payload = json.loads(_b64u_decode(body))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


# ─── Dependencies ─────────────────────────────────────────────────────────────

def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


async def require_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Require a valid login token; returns the current User or 401."""
    token = _bearer(authorization)
    payload = _verify_token(token) if token else None
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = (await db.execute(select(User).where(User.id == payload["uid"]))).scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


async def require_admin(user: User = Depends(require_user)) -> User:
    """Require a logged-in user with the admin role."""
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Machine auth for ingestion. No-op when FMS_API_KEY is not configured."""
    api_key = settings.fms_api_key.strip()
    if not api_key:
        return
    if x_api_key != api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-API-Key",
        )


def client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def resolve_actor(body_actor: str | None, header_actor: str | None) -> str:
    for candidate in (body_actor, header_actor):
        if candidate and candidate.strip():
            return candidate.strip()[:120]
    return "analyst"
