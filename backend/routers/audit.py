"""System-wide user activity log — who did what, powering the corner Activity widget."""
import csv
import io
import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
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


def _date_filters(date_from: date | None, date_to: date | None) -> list:
    """Inclusive day bounds on created_at — same convention as cases and reports,
    so a range means the whole of both end days regardless of the view."""
    filters = []
    if date_from:
        filters.append(AuditLog.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        filters.append(AuditLog.created_at <= datetime.combine(date_to, datetime.max.time()))
    return filters


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
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    q = select(AuditLog)
    if username:
        q = q.where(AuditLog.username == username)
    for f in _date_filters(date_from, date_to):
        q = q.where(f)
    q = q.order_by(AuditLog.created_at.desc()).limit(limit)
    return list((await db.execute(q)).scalars().all())


@router.get("/security")
async def list_security_events(
    limit: int = Query(100, ge=1, le=500),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Security-relevant events only — sign-ins and failures, rate-limiting,
    rejected ingestion API keys, OFAC sanctions hits, and account/role changes.
    Powers the Security Events view. Admin-only.

    The counts below are computed over the rows actually returned, so they follow
    whatever date range was requested rather than reporting all-time totals.
    """
    q = select(AuditLog).where(AuditLog.action.in_(SECURITY_ACTIONS))
    for f in _date_filters(date_from, date_to):
        q = q.where(f)
    rows = list((await db.execute(
        q.order_by(AuditLog.created_at.desc()).limit(limit)
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


@router.get("/export")
async def export_audit(
    username: str | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    limit: int = Query(10000, ge=1, le=100000),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """The audit trail as CSV for the requested range.

    Examiners ask for "every action between these two dates" — this returns
    exactly the rows the Audit Trail screen is showing, same filters, so the
    export can never disagree with what was on screen. Admin-only.
    """
    q = select(AuditLog)
    if username:
        q = q.where(AuditLog.username == username)
    for f in _date_filters(date_from, date_to):
        q = q.where(f)
    rows = list((await db.execute(
        q.order_by(AuditLog.created_at.desc()).limit(limit)
    )).scalars().all())

    columns = ["timestamp", "username", "action", "target", "detail", "ip"]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns)
    writer.writeheader()
    for r in rows:
        writer.writerow({
            "timestamp": r.created_at.isoformat() if r.created_at else "",
            "username": r.username,
            "action": r.action,
            "target": r.target or "",
            "detail": r.detail or "",
            "ip": r.ip or "",
        })
    buf.seek(0)

    span = f"_{date_from or 'start'}_to_{date_to or 'now'}"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="fms_audit_trail{span}.csv"'},
    )


@router.get("/users")
async def audit_users(
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Per-user activity summary — everyone who acted in the system, with counts
    and last-seen, for user-centric investigation. Honours the same date range as
    the other audit views so one control filters the whole page consistently."""
    from sqlalchemy import func
    q = select(
        AuditLog.username,
        func.count().label("actions"),
        func.max(AuditLog.created_at).label("last_activity"),
        func.sum(case((AuditLog.action == "LOGIN_FAILED", 1), else_=0)).label("failed_logins"),
        func.sum(case((AuditLog.action.like("CASE_%"), 1), else_=0)).label("case_actions"),
    )
    for f in _date_filters(date_from, date_to):
        q = q.where(f)
    rows = (await db.execute(
        q.group_by(AuditLog.username).order_by(func.max(AuditLog.created_at).desc())
    )).all()
    return [
        {"username": r.username, "actions": int(r.actions or 0),
         "failed_logins": int(r.failed_logins or 0), "case_actions": int(r.case_actions or 0),
         "last_activity": str(r.last_activity) if r.last_activity else None}
        for r in rows
    ]
