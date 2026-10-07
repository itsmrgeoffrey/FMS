"""Approval queue for dual-controlled administrative changes (maker-checker).

Admins see pending changes requested by other admins and approve or reject
them. The requester (maker) can cancel their own request but can never approve
it — the whole point is a second pair of eyes.
"""
import logging
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, update
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


def _approval_out(approval: PendingApproval) -> dict:
    result = ApprovalOut.model_validate(approval).model_dump()
    payload = json.loads(approval.payload)
    if dual_control.requires_independent_approval(approval.action, payload):
        from backend.services.rule_governance import revision
        rules = payload.get("rules") is not None
        allowed = {"ctr_thresholds", "sar_ratio", "structuring_band_ratio", "rolling_window_days", "smurfing_window_hours"} if rules else {
            "regulatory_jurisdiction", "institution_type", "business_timezone"}
        # Never expose the raw settings payload: other sections may contain secrets.
        result["configuration_proposal"] = {
            "kind": "rules" if rules else "operating_profile",
            "before": {k: v for k, v in payload.get("configuration_before", {}).items() if k in allowed},
            "proposed": {k: v for k, v in payload.get("rules" if rules else "operating_profile", {}).items() if k in allowed},
            "rationale": payload.get("rules_rationale" if rules else "profile_rationale") or "No reason recorded",
            "stale": payload.get("rules_base_version" if rules else "configuration_revision") != revision(),
            "initial_configuration_allowed": bool(payload.get("rules_allow_empty_history")) if rules else False,
        }
    return result


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
        "pending": [_approval_out(a) for a in pending],
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

    decision = await db.execute(update(PendingApproval).where(
        PendingApproval.id == approval.id, PendingApproval.status == "pending").values(
            status="rejected", decided_by=admin.username, decided_at=datetime.utcnow(),
            decision_note=(body.note or "").strip() or None))
    if decision.rowcount != 1:
        raise HTTPException(409, "This proposal is no longer pending.")
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

    decision = await db.execute(update(PendingApproval).where(
        PendingApproval.id == approval.id, PendingApproval.status == "pending").values(
            status="cancelled", decided_by=admin.username, decided_at=datetime.utcnow()))
    if decision.rowcount != 1:
        raise HTTPException(409, "This proposal is no longer pending.")
    await db.commit()
    await audit.record(admin.username, "CHANGE_CANCELLED", target=approval.target,
                       detail=f"[{approval.id[:8]}] {approval.summary}", request=request)
    return {"cancelled": True}
