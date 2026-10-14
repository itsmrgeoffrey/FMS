"""Case ownership, maker-checker dispositions, and durable bulk execution."""
import asyncio
import logging
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select

from backend.auth import role_has
from backend.database import SessionLocal
from backend.models import AuditLog, CaseAction, CaseBatch, CaseDecision, FraudCase, User
from backend.services import callbacks, delivery
from backend.services.broadcaster import broadcaster

log = logging.getLogger(__name__)
FINAL_STATUSES = {"CONFIRMED_FRAUD", "DISMISSED"}
PROPOSAL_ACTIONS = {"CONFIRMED", "DISMISSED"}
_batch_lock = asyncio.Lock()


def _note(value: str | None) -> str:
    return (value or "").strip()


def _require(capability: str, user: User) -> None:
    if not role_has(user.role, capability):
        label = "analyst/inputter" if capability == "act" else "case approver"
        raise HTTPException(403, f"This action requires the {label} role")


def _require_owner(case: FraudCase, user: User) -> None:
    if case.assigned_to != user.username:
        if case.assigned_to:
            raise HTTPException(409, f"This case is assigned to {case.assigned_to}")
        raise HTTPException(409, "Start review and claim this case before submitting a decision")


def _record(db, case: FraudCase, action: str, user: User, note: str | None) -> None:
    db.add(CaseAction(case_id=case.id, action=action, actor=user.username, note=note or None))
    case.updated_at = datetime.utcnow()


async def apply_action(db, case: FraudCase, user: User, action: str, note: str | None,
                       batch_id: str | None = None) -> CaseDecision | None:
    """Apply a non-final review action or submit a final disposition proposal."""
    action = action.upper()
    reason = _note(note)
    if case.status in FINAL_STATUSES:
        raise HTTPException(409, "This case is closed")
    if case.status == "PENDING_APPROVAL":
        raise HTTPException(409, "This case already has a disposition awaiting approval")
    if case.status == "CLEAN" and not (case.ctr_required or case.sar_recommended or case.sanctions_hit):
        raise HTTPException(409, "This transaction has no outstanding review")

    if action == "REVIEW":
        if case.status == "ESCALATED" or case.review_level == "SENIOR":
            _require("approve_case", user)
            case.review_level = "SENIOR"
        else:
            _require("act", user)
            case.review_level = "STANDARD"
        if case.assigned_to and case.assigned_to != user.username:
            raise HTTPException(409, f"This case is already assigned to {case.assigned_to}")
        case.status = "UNDER_REVIEW"
        case.assigned_to = user.username
        case.assigned_at = datetime.utcnow()
        case.review_due_at = datetime.utcnow() + timedelta(days=1)
        _record(db, case, "REVIEW", user, reason)
        return None

    if action == "RELEASED":
        _require("approve_case" if case.review_level == "SENIOR" else "act", user)
        _require_owner(case, user)
        case.status = "ESCALATED" if case.review_level == "SENIOR" else "OPEN"
        case.assigned_to = case.assigned_at = case.review_due_at = None
        _record(db, case, "RELEASED", user, reason)
        return None

    if action == "ESCALATED":
        _require("act", user)
        if case.review_level == "SENIOR":
            raise HTTPException(409, "This case is already routed for senior review")
        if not reason:
            raise HTTPException(422, "An escalation reason is required")
        if case.assigned_to and case.assigned_to != user.username:
            raise HTTPException(409, f"This case is assigned to {case.assigned_to}")
        case.status = "ESCALATED"
        case.review_level = "SENIOR"
        case.assigned_to = case.assigned_at = case.review_due_at = None
        _record(db, case, "ESCALATED", user, reason)
        return None

    if action == "NOTE_ADDED":
        if not reason:
            raise HTTPException(422, "A note is required")
        if case.review_level == "SENIOR":
            _require("approve_case", user)
        else:
            _require("act", user)
        _record(db, case, "NOTE_ADDED", user, reason)
        return None

    if action not in PROPOSAL_ACTIONS:
        raise HTTPException(400, "Choose REVIEW, RELEASED, ESCALATED, CONFIRMED, DISMISSED, or NOTE_ADDED")
    if not reason:
        raise HTTPException(422, "A disposition rationale is required")
    if case.status != "UNDER_REVIEW":
        raise HTTPException(409, "Start review before submitting a disposition")
    _require_owner(case, user)
    _require("approve_case" if case.review_level == "SENIOR" else "act", user)

    proposal = CaseDecision(
        case_id=case.id,
        proposed_action=action,
        rationale=reason,
        requested_by=user.username,
        batch_id=batch_id,
    )
    case.decisions.append(proposal)
    db.add(proposal)
    case.status = "PENDING_APPROVAL"
    _record(db, case, "FRAUD_PROPOSED" if action == "CONFIRMED" else "DISMISSAL_PROPOSED", user, reason)
    delivery.enqueue(db, "case.decision_requested", {
        **callbacks.case_payload(case),
        "proposed_action": action,
        "requested_by": user.username,
        "rationale": reason,
    })
    return proposal


async def decide(db, case: FraudCase, user: User, approve: bool, note: str | None,
                 batch_id: str | None = None) -> CaseDecision:
    _require("approve_case", user)
    proposal = case.pending_decision
    if case.status != "PENDING_APPROVAL" or not proposal:
        raise HTTPException(409, "This case has no pending disposition")
    if proposal.requested_by == user.username:
        raise HTTPException(403, "You submitted this decision; a different approver must decide it")
    reason = _note(note)
    if not approve and not reason:
        raise HTTPException(422, "A rejection reason is required")

    proposal.status = "approved" if approve else "rejected"
    proposal.decided_by = user.username
    proposal.decided_at = datetime.utcnow()
    proposal.decision_note = reason or None
    proposal.batch_id = proposal.batch_id or batch_id
    if approve:
        case.status = "CONFIRMED_FRAUD" if proposal.proposed_action == "CONFIRMED" else "DISMISSED"
        case.assigned_to = case.assigned_at = case.review_due_at = None
        _record(db, case, "DECISION_APPROVED", user, reason or f"Approved {proposal.proposed_action.lower()} disposition")
        payload = callbacks.case_payload(case)
        payload["disposition"] = {
            "action": proposal.proposed_action,
            "proposed_by": proposal.requested_by,
            "approved_by": user.username,
            "rationale": proposal.rationale,
            "decision_note": reason or None,
        }
        payload["reporting_obligations_unchanged"] = True
        delivery.enqueue(db, "case.disposition", payload)
    else:
        case.status = "UNDER_REVIEW"
        case.assigned_to = proposal.requested_by
        case.assigned_at = datetime.utcnow()
        case.review_due_at = datetime.utcnow() + timedelta(days=1)
        _record(db, case, "DECISION_REJECTED", user, reason)
    return proposal


async def cancel_proposal(db, case: FraudCase, user: User) -> CaseDecision:
    proposal = case.pending_decision
    if case.status != "PENDING_APPROVAL" or not proposal:
        raise HTTPException(409, "This case has no pending disposition")
    if proposal.requested_by != user.username:
        raise HTTPException(403, "Only the inputter who submitted this decision can withdraw it")
    proposal.status = "cancelled"
    proposal.decided_by = user.username
    proposal.decided_at = datetime.utcnow()
    case.status = "UNDER_REVIEW"
    case.assigned_to = user.username
    _record(db, case, "DECISION_CANCELLED", user, "Disposition proposal withdrawn")
    return proposal


async def _run_batch(batch_id: str) -> None:
    while True:
        async with SessionLocal() as db:
            batch = (await db.execute(select(CaseBatch).where(CaseBatch.id == batch_id)
                .with_for_update())).scalar_one_or_none()
            if not batch or batch.status in {"COMPLETED", "FAILED"}:
                return
            chunk = list(batch.case_ids or [])[batch.processed:batch.processed + 100]
            if not chunk:
                batch.status = "COMPLETED"
                batch.completed_at = datetime.utcnow()
                await db.commit()
                await broadcaster.broadcast({"event": "case_batch_completed", "batch_id": batch_id})
                return
            batch.status = "RUNNING"
            user = (await db.execute(select(User).where(
                User.username == batch.requested_by, User.is_active == True  # noqa: E712
            ))).scalar_one_or_none()
            if not user:
                batch.status = "FAILED"
                batch.errors = [*batch.errors, {"error": "Requesting user is no longer active"}]
                batch.completed_at = datetime.utcnow()
                await db.commit()
                return
            rows = (await db.execute(select(FraudCase).where(FraudCase.id.in_(chunk))
                .order_by(FraudCase.id).with_for_update())).scalars().all()
            by_id = {case.id: case for case in rows}
            errors = list(batch.errors or [])
            for case_id in chunk:
                case = by_id.get(case_id)
                try:
                    if not case:
                        raise HTTPException(404, "Case not found")
                    if batch.action == "APPROVE":
                        await decide(db, case, user, True, batch.rationale, batch.id)
                    elif batch.action == "REJECT":
                        await decide(db, case, user, False, batch.rationale, batch.id)
                    else:
                        await apply_action(db, case, user, batch.action, batch.rationale, batch.id)
                    db.add(AuditLog(username=user.username, action=f"CASE_{batch.action}", target=case_id,
                        detail=f"[batch {batch.id[:8]}] {batch.rationale}"))
                    batch.succeeded += 1
                except HTTPException as exc:
                    batch.failed += 1
                    if len(errors) < 100:
                        errors.append({"case_id": case_id, "error": str(exc.detail)})
                batch.processed += 1
            batch.errors = errors
            await db.commit()
        await broadcaster.broadcast({"event": "case_batch_progress", "batch_id": batch_id})

async def batch_loop() -> None:
    while True:
        try:
            async with _batch_lock:
                async with SessionLocal() as db:
                    pending = (await db.execute(select(CaseBatch.id).where(
                        CaseBatch.status.in_(("PENDING", "RUNNING"))
                    ).order_by(CaseBatch.created_at).limit(1))).scalar_one_or_none()
                if pending:
                    await _run_batch(pending)
        except Exception:
            log.exception("Case batch execution failed")
        await asyncio.sleep(2)
