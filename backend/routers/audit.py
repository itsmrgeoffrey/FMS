"""System-wide user activity log — who did what, powering the corner Activity widget."""
import logging

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import client_ip, require_user
from backend.database import SessionLocal, get_db
from backend.models import AuditLog, User
from backend.schemas import AuditOut

log = logging.getLogger(__name__)

router = APIRouter(prefix="/audit", tags=["audit"])


async def record(username: str, action: str, target: str | None = None,
                 detail: str | None = None, request: Request | None = None) -> None:
    """Write one audit entry. Best-effort — never let logging break the action."""
    try:
        async with SessionLocal() as db:
            db.add(AuditLog(
                username=username,
                action=action,
                target=target,
                detail=detail,
                ip=client_ip(request) if request else None,
            ))
            await db.commit()
    except Exception as e:
        log.warning(f"Audit log write failed ({action} by {username}): {e}")


@router.get("", response_model=list[AuditOut])
async def list_audit(
    limit: int = Query(50, ge=1, le=200),
    _user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    return list((await db.execute(q)).scalars().all())
