"""Dual control (maker-checker) for sensitive administrative actions.

Banking practice: no single person should be able to change who has access to
the system or how it is configured. FMS implements this as *dual control*:

- The admin who requests a sensitive change is the **maker**. The change is not
  applied; it is queued as a ``PendingApproval``.
- A **different** admin (the **checker**) must approve it before it executes.
  Makers cannot approve their own requests.
- Every step — request, approval, rejection, cancellation — is written to the
  audit log.

Covered actions: creating users, changing roles, enabling/disabling accounts,
resetting another admin's password, and settings changes.

**Single-admin mode:** dual control requires two people. When fewer than two
active local admins exist (e.g. a fresh install), actions execute immediately —
otherwise the first admin could never create the second. The response says so
explicitly, and the audit entry is tagged, so the state is visible rather than
silent. Institutions should create a second admin promptly; dual control
activates by itself the moment they do.

Executors are registered by the modules that own the logic (auth_routes,
settings) via :func:`register`, which keeps this module free of circular
imports. An executor receives the JSON payload stored at request time and
performs the change *at approval time* — so it must re-validate state, since
the world may have moved on between request and approval.
"""
import json
import logging
from datetime import datetime
from typing import Awaitable, Callable

from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import PendingApproval, User

log = logging.getLogger(__name__)

# action name -> async executor(db, payload, actor_username, request) -> result dict
Executor = Callable[[AsyncSession, dict, str, Request | None], Awaitable[dict]]
EXECUTORS: dict[str, Executor] = {}


def register(action: str) -> Callable[[Executor], Executor]:
    """Decorator: register the function that actually applies `action`."""
    def _wrap(fn: Executor) -> Executor:
        EXECUTORS[action] = fn
        return fn
    return _wrap


async def active_admin_count(db: AsyncSession) -> int:
    return (await db.execute(
        select(func.count()).select_from(User).where(User.role == "admin", User.is_active == True)  # noqa: E712
    )).scalar_one()


async def dual_control_active(db: AsyncSession) -> bool:
    """Maker-checker is enforceable only when a second admin exists to check."""
    return (await active_admin_count(db)) >= 2


async def submit_or_execute(
    db: AsyncSession,
    request: Request | None,
    admin: User,
    action: str,
    payload: dict,
    summary: str,
    target: str | None = None,
) -> dict:
    """Queue `action` for a second admin's approval, or execute it immediately
    when dual control is inactive (fewer than two active admins)."""
    from backend.routers import audit  # local import to avoid a cycle

    if action not in EXECUTORS:
        raise HTTPException(status_code=500, detail=f"No executor registered for action {action!r}")

    if await dual_control_active(db):
        approval = PendingApproval(
            action=action,
            payload=json.dumps(payload),
            target=target,
            summary=summary,
            requested_by=admin.username,
        )
        db.add(approval)
        await db.commit()
        await db.refresh(approval)
        await audit.record(admin.username, "CHANGE_REQUESTED", target=target,
                           detail=f"[{approval.id[:8]}] {summary}", request=request)
        return {
            "pending": True,
            "approval_id": approval.id,
            "summary": summary,
            "message": "Dual control is active: a second admin must approve this change before it takes effect.",
        }

    result = await EXECUTORS[action](db, payload, admin.username, request)
    await audit.record(admin.username, "DUAL_CONTROL_INACTIVE", target=target,
                       detail=f"{summary} (applied immediately: fewer than two active admins)", request=request)
    return {"pending": False, "dual_control": "inactive", **result}


async def execute_approval(
    db: AsyncSession,
    request: Request | None,
    checker: User,
    approval: PendingApproval,
) -> dict:
    """Run an approved change. Caller has already verified maker != checker and
    status == pending."""
    executor = EXECUTORS.get(approval.action)
    if executor is None:
        raise HTTPException(status_code=500, detail=f"No executor registered for action {approval.action!r}")
    result = await executor(db, json.loads(approval.payload), checker.username, request)
    approval.status = "approved"
    approval.decided_by = checker.username
    approval.decided_at = datetime.utcnow()
    await db.commit()
    return result
