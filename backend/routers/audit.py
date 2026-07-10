"""System-wide user activity log — who did what, powering the corner Activity widget."""
import logging

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import client_ip, require_admin, require_user
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
    limit: int = Query(50, ge=1, le=500),
    username: str | None = Query(None),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    q = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if username:
        q = q.where(AuditLog.username == username)
    return list((await db.execute(q)).scalars().all())


@router.get("/users")
async def audit_users(_admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """Per-user activity summary — everyone who has ever acted in the system,
    with counts and last-seen, for user-centric investigation."""
    from sqlalchemy import func
    rows = (await db.execute(
        select(
            AuditLog.username,
            func.count().label("actions"),
            func.max(AuditLog.created_at).label("last_activity"),
            func.sum(case((AuditLog.action == "LOGIN_FAILED", 1), else_=0)).label("failed_logins"),
            func.sum(case((AuditLog.action.like("CASE_%"), 1), else_=0)).label("case_actions"),
        )
        .group_by(AuditLog.username)
        .order_by(func.max(AuditLog.created_at).desc())
    )).all()
    return [
        {"username": r.username, "actions": int(r.actions or 0),
         "failed_logins": int(r.failed_logins or 0), "case_actions": int(r.case_actions or 0),
         "last_activity": str(r.last_activity) if r.last_activity else None}
        for r in rows
    ]
