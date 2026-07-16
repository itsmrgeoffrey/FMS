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

# Security-relevant actions, surfaced in the Security Events view. These are
# ordinary audit records; this set just classifies which ones are security
# signals (authentication, access control, sanctions, API-key abuse).
SECURITY_ACTIONS = {
    "LOGIN", "LOGIN_FAILED", "LOGIN_RATE_LIMITED", "SIGNUP",
    "PASSWORD_CHANGED", "PASSWORD_RESET_REQUESTED", "USER_PASSWORD_RESET",
    "USER_CREATED", "USER_ROLE_CHANGED", "USER_ENABLED", "USER_DISABLED",
    "INGEST_KEY_REJECTED", "SANCTIONS_HIT",
}

# Visual emphasis in the UI. Anything unlisted is treated as "info".
SECURITY_SEVERITY = {
    "SANCTIONS_HIT": "critical",
    "LOGIN_FAILED": "warning",
    "LOGIN_RATE_LIMITED": "warning",
    "INGEST_KEY_REJECTED": "warning",
    "USER_DISABLED": "notice",
    "USER_ROLE_CHANGED": "notice",
    "USER_PASSWORD_RESET": "notice",
}


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


@router.get("/security")
async def list_security_events(
    limit: int = Query(100, ge=1, le=500),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Security-relevant events only — sign-ins and failures, rate-limiting,
    rejected ingestion API keys, OFAC sanctions hits, and account/role changes.
    Powers the Security Events view. Admin-only."""
    rows = list((await db.execute(
        select(AuditLog)
        .where(AuditLog.action.in_(SECURITY_ACTIONS))
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )).scalars().all())
    counts = {
        "failed_logins": sum(1 for r in rows if r.action == "LOGIN_FAILED"),
        "rejected_keys": sum(1 for r in rows if r.action == "INGEST_KEY_REJECTED"),
        "sanctions_hits": sum(1 for r in rows if r.action == "SANCTIONS_HIT"),
    }
    return {
        "counts": counts,
        "events": [
            {
                "id": r.id, "username": r.username, "action": r.action,
                "severity": SECURITY_SEVERITY.get(r.action, "info"),
                "target": r.target, "detail": r.detail, "ip": r.ip,
                "created_at": str(r.created_at),
            }
            for r in rows
        ],
    }


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
