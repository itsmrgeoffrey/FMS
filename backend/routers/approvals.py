"""Approval queue for dual-controlled administrative changes (maker-checker).

Admins see pending changes requested by other admins and approve or reject
them. The requester (maker) can cancel their own request but can never approve
it — the whole point is a second pair of eyes.
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import require_admin
from backend.database import get_db
from backend.models import PendingApproval, User
from backend.routers import audit
from backend.services import dual_control

log = logging.getLogger(__name__)

router = APIRouter(prefix="/approvals", tags=["approvals"], dependencies=[Depends(require_admin)])


class ApprovalOut(BaseModel):
    id: str
    action: str
    target: str | None
    summary: str
    requested_by: str
    requested_at: datetime
    status: str
    decided_by: str | None
    decided_at: datetime | None
    decision_note: str | None

    model_config = {"from_attributes": True}


class DecisionNote(BaseModel):
    note: str | None = None


async def _get_approval(db: AsyncSession, approval_id: str) -> PendingApproval:
    approval = (await db.execute(
        select(PendingApproval).where(PendingApproval.id == approval_id)
    )).scalar_one_or_none()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    return approval


@router.get("")
async def list_approvals(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    pending = (await db.execute(
        select(PendingApproval).where(PendingApproval.status == "pending")
        .order_by(PendingApproval.requested_at)
    )).scalars().all()
    recent = (await db.execute(
        select(PendingApproval).where(PendingApproval.status != "pending")
        .order_by(PendingApproval.decided_at.desc()).limit(20)
    )).scalars().all()
    return {
        "dual_control_active": await dual_control.dual_control_active(db),
        "active_admins": await dual_control.active_admin_count(db),
        "me": admin.username,
        "pending": [ApprovalOut.model_validate(a).model_dump() for a in pending],
        "recent": [ApprovalOut.model_validate(a).model_dump() for a in recent],
    }


@router.post("/{approval_id}/approve")
async def approve(
    approval_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    approval = await _get_approval(db, approval_id)
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail=f"This change was already {approval.status}")
    if approval.requested_by == admin.username:
        raise HTTPException(status_code=403, detail="You requested this change — a different admin must approve it")

    result = await dual_control.execute_approval(db, request, admin, approval)
    await audit.record(admin.username, "CHANGE_APPROVED", target=approval.target,
                       detail=f"[{approval.id[:8]}] {approval.summary} (requested by {approval.requested_by})",
                       request=request)
    return {"approved": True, "summary": approval.summary, "result": result}


@router.post("/{approval_id}/reject")
async def reject(
    approval_id: str,
    body: DecisionNote,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    approval = await _get_approval(db, approval_id)
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail=f"This change was already {approval.status}")
    if approval.requested_by == admin.username:
        raise HTTPException(status_code=403, detail="Use cancel to withdraw your own request")

    approval.status = "rejected"
    approval.decided_by = admin.username
    approval.decided_at = datetime.utcnow()
    approval.decision_note = (body.note or "").strip() or None
    await db.commit()
    await audit.record(admin.username, "CHANGE_REJECTED", target=approval.target,
                       detail=f"[{approval.id[:8]}] {approval.summary}" + (f" — {approval.decision_note}" if approval.decision_note else ""),
                       request=request)
    return {"rejected": True}


@router.post("/{approval_id}/cancel")
async def cancel(
    approval_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    approval = await _get_approval(db, approval_id)
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail=f"This change was already {approval.status}")
    if approval.requested_by != admin.username:
        raise HTTPException(status_code=403, detail="Only the requester can cancel; use reject instead")

    approval.status = "cancelled"
    approval.decided_by = admin.username
    approval.decided_at = datetime.utcnow()
    await db.commit()
    await audit.record(admin.username, "CHANGE_CANCELLED", target=approval.target,
                       detail=f"[{approval.id[:8]}] {approval.summary}", request=request)
    return {"cancelled": True}
