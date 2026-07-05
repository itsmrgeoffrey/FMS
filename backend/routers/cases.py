from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import require_user
from backend.database import get_db
from backend.models import FraudCase, CaseAction, User
from backend.routers import audit
from backend.schemas import FraudCaseOut, FraudCaseListItem, CaseActionCreate, CasesPage

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
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    filters = []
    if status:
        filters.append(FraudCase.status == status)
    if confidence:
        filters.append(FraudCase.confidence == confidence)
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
        .order_by(FraudCase.created_at.desc())
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
    user: User = Depends(require_user),
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
