import asyncio
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import require_user, require_case_action
from backend.database import get_db
from backend.models import FraudCase, CaseAction, User
from backend.routers import audit
from backend.schemas import FraudCaseOut, FraudCaseListItem, CaseActionCreate, CasesPage
from backend.services import callbacks, delivery
from backend.services.review import open_condition, flagged_condition

router = APIRouter(prefix="/cases", tags=["cases"], dependencies=[Depends(require_user)])

STATUS_TRANSITIONS = {
    "DISMISSED": "DISMISSED",
    "CONFIRMED": "CONFIRMED_FRAUD",
    "ESCALATED": "ESCALATED",
    "REVIEW": "UNDER_REVIEW",
    "NOTE_ADDED": None,  # no status change
}


@router.get("", response_model=CasesPage)
async def list_cases(
    status: str | None = Query(None),
    confidence: str | None = Query(None),
    review_required: bool | None = Query(None),
    result: str | None = Query(None, pattern="^(flagged|clean)$"),
    sort: str = Query("recent", pattern="^(recent|risk)$"),
    search: str | None = Query(None, max_length=200),
    flag: str | None = Query(None, pattern="^(ctr|sar|sanctions)$"),
    min_risk: int | None = Query(None, ge=0, le=100),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    filters = []
    if review_required:
        filters.append(open_condition())
    if result:
        filters.append(flagged_condition() if result == "flagged" else ~flagged_condition())
    if status:
        filters.append(FraudCase.status == status)
    if confidence:
        filters.append(FraudCase.confidence == confidence)
    if search and search.strip():
        # Escape LIKE metacharacters so account identifiers are searched literally.
        term = search.strip().replace("/", "//").replace("%", "/%").replace("_", "/_")
        filters.append(or_(*(column.ilike(f"%{term}%", escape="/") for column in (
            FraudCase.account_id, FraudCase.counterparty_account, FraudCase.counterparty_name,
            FraudCase.source_table, FraudCase.source_txn_id, FraudCase.channel,
            FraudCase.reference, FraudCase.id,
        ))))
    if flag:
        filters.append({"ctr": FraudCase.ctr_required, "sar": FraudCase.sar_recommended,
                        "sanctions": FraudCase.sanctions_hit}[flag].is_(True))
    if min_risk is not None:
        filters.append(FraudCase.risk_score >= min_risk)
    if date_from:
        filters.append(FraudCase.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        filters.append(FraudCase.created_at <= datetime.combine(date_to, datetime.max.time()))

    where = and_(*filters) if filters else True

    total_q = await db.execute(select(func.count()).select_from(FraudCase).where(where))
    total = total_q.scalar_one()

    q = (
        select(FraudCase)
        .where(where)
        .order_by(*( (FraudCase.risk_score.desc(), FraudCase.created_at.desc(), FraudCase.id)
                    if sort == "risk" else (FraudCase.created_at.desc(), FraudCase.id) ))
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(q)
    cases = result.scalars().all()

    return CasesPage(
        items=[FraudCaseListItem.model_validate(c) for c in cases],
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/{case_id}", response_model=FraudCaseOut)
async def get_case(case_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(FraudCase)
        .where(FraudCase.id == case_id)
        .options(selectinload(FraudCase.actions))
    )
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return FraudCaseOut.model_validate(case)


@router.post("/{case_id}/actions", response_model=FraudCaseOut)
async def add_action(
    case_id: str,
    body: CaseActionCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_case_action),
):
    result = await db.execute(
        select(FraudCase)
        .where(FraudCase.id == case_id)
        .options(selectinload(FraudCase.actions))
    )
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    action_key = body.action.upper()
    if action_key not in STATUS_TRANSITIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid action. Choose from: {', '.join(STATUS_TRANSITIONS)}"
        )

    new_status = STATUS_TRANSITIONS[action_key]
    if new_status and case.status in ("CONFIRMED_FRAUD", "DISMISSED"):
        raise HTTPException(409, "This case is closed")
    if new_status and case.status == "CLEAN" and not (case.ctr_required or case.sar_recommended or case.sanctions_hit):
        raise HTTPException(409, "This transaction has no outstanding review")
    if action_key in ("DISMISSED", "CONFIRMED", "ESCALATED") and not (body.note or "").strip():
        raise HTTPException(422, "A disposition reason is required")
    if new_status:
        case.status = new_status
        case.updated_at = datetime.utcnow()

    action = CaseAction(
        case_id=case_id,
        action=action_key,
        actor=user.username,   # trusted: from the authenticated session, not client input
        note=body.note,
    )
    db.add(action)
    if new_status:
        payload = callbacks.case_payload(case)
        payload["disposition"] = {"action": action_key, "by": user.username, "note": body.note}
        payload["reporting_obligations_unchanged"] = True
        delivery.enqueue(db, "case.disposition", payload)
    await db.commit()
    await db.refresh(case)

    await audit.record(
        user.username, f"CASE_{action_key}", target=case_id,
        detail=body.note, request=request,
    )

    result2 = await db.execute(
        select(FraudCase)
        .where(FraudCase.id == case_id)
        .options(selectinload(FraudCase.actions))
    )
    case = result2.scalar_one()
    return FraudCaseOut.model_validate(case)
