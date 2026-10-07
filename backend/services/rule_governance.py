"""Durable, version-checked changes to the small installation's detection rules."""
import asyncio
import hashlib
import json
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select, update

from backend.models import AuditLog, PendingApproval, RuleChange, User
from backend.services import analyzer

_change_lock = asyncio.Lock()


def revision() -> str:
    from backend.services.installation import profile
    value = json.dumps({"rules": analyzer.snapshot_rules(), "profile": profile()}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(value.encode()).hexdigest()


async def restore_latest(db):
    from backend.services.installation import activate
    saved_profile = (await db.execute(select(AuditLog).where(AuditLog.action == "PROFILE_UPDATED")
        .order_by(AuditLog.id.desc()).limit(1))).scalar_one_or_none()
    if saved_profile:
        activate(json.loads(saved_profile.detail)["new_values"])
    row = (await db.execute(select(RuleChange).order_by(RuleChange.id.desc()).limit(1))).scalar_one_or_none()
    if row and (row.backtest or {}).get("storage_version") == 1:
        analyzer.validate_rule_overrides(row.new_values)
        analyzer.restore_rules(row.new_values)


async def _commit_change(db, approval, actor):
    if approval is not None:
        if approval.requested_by == actor:
            raise HTTPException(403, "A different administrator must approve this change.")
        admins = (await db.execute(select(User.username).where(
            User.username.in_([approval.requested_by, actor]),
            User.role == "admin", User.is_active.is_(True)))).scalars().all()
        if len(set(admins)) != 2:
            raise HTTPException(403, "Both requester and approver must still be active administrators.")
        decision = await db.execute(update(PendingApproval).where(
            PendingApproval.id == approval.id, PendingApproval.status == "pending",
            PendingApproval.action == "SETTINGS_UPDATE").values(
                status="approved", decided_by=actor, decided_at=datetime.utcnow()))
        if decision.rowcount != 1:
            raise HTTPException(409, "This proposal is no longer pending.")
        db.add(AuditLog(username=actor, action="CONFIGURATION_APPROVED", target=approval.id,
                        detail=f"Requested by {approval.requested_by}; approved by {actor}. {approval.summary}"))
    await db.commit()


async def apply_profile(db, value, rationale, base_version, actor, *, approval=None):
    from backend.services.installation import OperatingProfile, activate, profile
    async with _change_lock:
        if base_version != revision():
            raise HTTPException(409, "Configuration changed. Reload the installation profile.")
        if not (rationale or "").strip():
            raise HTTPException(422, "A reason for the profile change is required.")
        checked = OperatingProfile(**value).model_dump()
        db.add(AuditLog(username=actor, action="PROFILE_UPDATED", target="installation",
                       detail=json.dumps({"old_values": profile(), "new_values": checked,
                                          "rationale": rationale.strip()})))
        await _commit_change(db, approval, actor)
        activate(checked)
        return {"saved": True, "restart_required": False}


async def apply_change(db, rules, rationale, base_version, actor, allow_empty=False, *, approval=None):
    from backend.routers.insights import BacktestRequest, run_rules_backtest
    from backend.services.installation import profile

    async with _change_lock:
        if base_version != revision():
            raise HTTPException(409, "Rules changed since this proposal was loaded. Reload and backtest again.")
        reason = (rationale or "").strip()
        if not reason:
            raise HTTPException(422, "A reason for the rule change is required.")
        try:
            analyzer.validate_rule_overrides(rules)
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        before = analyzer.snapshot_rules()
        result = await run_rules_backtest(BacktestRequest(proposed=rules), db)
        if not result["replayed"] and not allow_empty:
            raise HTTPException(422, "No replay history is available. Explicitly acknowledge initial configuration without historical validation.")
        # No await while changing globals: live processing sees a complete configuration.
        try:
            analyzer.apply_rule_overrides(rules)
            after = analyzer.snapshot_rules()
        finally:
            analyzer.restore_rules(before)
        if before == after:
            await _commit_change(db, approval, actor)
            return {"saved": False, "restart_required": False, "rules_revision": revision()}
        evidence = {**result, "storage_version": 1, "initial_configuration": not result["replayed"],
                    "operating_profile": profile(), "base_revision": base_version}
        if approval is not None:
            evidence["approval"] = {"id": approval.id, "requested_by": approval.requested_by,
                                    "approved_by": actor}
        db.add(RuleChange(changed_by=actor, old_values=before, new_values=after,
                          rationale=reason, backtest=evidence))
        db.add(AuditLog(username=actor, action="RULES_UPDATED", target="rules", detail=reason))
        # A failed database write must leave the live rules unchanged.
        await _commit_change(db, approval, actor)
        analyzer.restore_rules(after)
        return {"saved": True, "restart_required": False, "rules_revision": revision(),
                "backtest": result}
