"""Lightweight, optional API-key auth and actor identity.

If FMS_API_KEY is set in the environment, every request to a protected route
must send a matching `X-API-Key` header. If it is unset (the default), the API
is open — so local development and demos keep working with no configuration.
This lets an SME lock the deployment down for production with a single env var.

Actor identity: mutating endpoints record *who* took an action. The actor comes
from the request body, then the `X-Actor` header, then defaults to "analyst".
"""
from fastapi import Header, HTTPException, status

from backend.config import settings


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """FastAPI dependency. No-op when FMS_API_KEY is not configured."""
    api_key = settings.fms_api_key.strip()
    if not api_key:
        return
    if x_api_key != api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-API-Key",
        )


def resolve_actor(body_actor: str | None, header_actor: str | None) -> str:
    for candidate in (body_actor, header_actor):
        if candidate and candidate.strip():
            return candidate.strip()[:120]
    return "analyst"
