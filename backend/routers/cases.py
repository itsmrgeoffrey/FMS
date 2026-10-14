from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.auth import require_case_approver, require_user, role_has
from backend.database import get_db
from backend.models import CaseBatch, FraudCase, User
from backend.routers import audit
from backend.schemas import CaseActionCreate, CasesPage, FraudCaseListItem, FraudCaseOut, UTCResponse
from backend.services import case_workflow
from backend.services.broadcaster import broadcaster
from backend.services.review import flagged_condition, open_condition, queue_condition

router = APIRouter(prefix="/cases", tags=["cases"], dependencies=[Depends(require_user)])


class DecisionBody(BaseModel):
    note: str | None = None


class BulkActionBody(BaseModel):
    action: str
    rationale: str = Field(min_length=1, max_length=2000)
    case_ids: list[str] = Field(default_factory=list, max_length=100_000)
    all_matching: bool = False
    filters: dict[str, str | int] = Field(default_factory=dict)

    @field_validator("rationale")
    @classmethod
    def nonblank_rationale(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A bulk action rationale is required")
        return value.strip()


class BulkFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str | None = None
    confidence: str | None = None
    result: Literal["flagged", "clean"] | None = None
    direction: Literal["INWARD", "OUTWARD"] | None = None
    search: str | None = Field(None, max_length=200)
    flag: Literal["ctr", "sar", "sanctions", "structuring"] | None = None
    min_risk: int | None = Field(None, ge=0, le=100)
    date_from: date | None = None
    date_to: date | None = None
    queue: Literal["review", "approvals", "escalations", "all"] | None = None


class BatchOut(UTCResponse):
    id: str
    action: str
    requested_by: str
    status: str
    total: int
    processed: int
    succeeded: int
    failed: int
    errors: list
    created_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}


def _filters(
    *, status: str | None = None, confidence: str | None = None,
    review_required: bool | None = None, result: str | None = None,
    direction: str | None = None, search: str | None = None,
    flag: str | None = None, min_risk: int | None = None,
    date_from: date | None = None, date_to: date | None = None,
    queue: str | None = None,
) -> list:
    filters = []
    if queue:
        filters.append(queue_condition(queue))
    elif review_required:
        filters.append(open_condition())
    if result:
        filters.append(flagged_condition() if result == "flagged" else ~flagged_condition())
    if direction:
        filters.append(FraudCase.direction == direction)
    if status:
        filters.append(FraudCase.status == status)
    if confidence:
        filters.append(FraudCase.confidence == confidence)
    if search and search.strip():
        term = search.strip().replace("/", "//").replace("%", "/%").replace("_", "/_")
        filters.append(or_(*(column.ilike(f"%{term}%", escape="/") for column in (
            FraudCase.account_id, FraudCase.counterparty_account, FraudCase.counterparty_name,
            FraudCase.source_table, FraudCase.source_txn_id, FraudCase.channel,
            FraudCase.reference, FraudCase.id,
        ))))
    if flag:
        filters.append({
            "ctr": FraudCase.ctr_required.is_(True),
            "sar": FraudCase.sar_recommended.is_(True),
            "sanctions": FraudCase.sanctions_hit.is_(True),
            "structuring": FraudCase.fraud_type == "cross-branch cash structuring",
        }[flag])
    if min_risk is not None:
        filters.append(FraudCase.risk_score >= min_risk)
    if date_from:
        filters.append(FraudCase.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        filters.append(FraudCase.created_at <= datetime.combine(date_to, datetime.max.time()))
    return filters


@router.get("", response_model=CasesPage)
async def list_cases(
    status: str | None = Query(None), confidence: str | None = Query(None),
    review_required: bool | None = Query(None),
    result: str | None = Query(None, pattern="^(flagged|clean)$"),
    direction: str | None = Query(None, pattern="^(INWARD|OUTWARD)$"),
    sort: str = Query("recent", pattern="^(recent|risk)$"),
    search: str | None = Query(None, max_length=200),
    flag: str | None = Query(None, pattern="^(ctr|sar|sanctions|structuring)$"),
    min_risk: int | None = Query(None, ge=0, le=100),
    date_from: date | None = Query(None), date_to: date | None = Query(None),
    queue: str | None = Query(None, pattern="^(review|approvals|escalations|all)$"),
    page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    conditions = _filters(status=status, confidence=confidence, review_required=review_required,
        result=result, direction=direction, search=search, flag=flag, min_risk=min_risk,
        date_from=date_from, date_to=date_to, queue=queue)
    where = and_(*conditions) if conditions else True
    total = (await db.execute(select(func.count()).select_from(FraudCase).where(where))).scalar_one()
    order = (FraudCase.risk_score.desc(), FraudCase.created_at.desc(), FraudCase.id) \
        if sort == "risk" else (FraudCase.created_at.desc(), FraudCase.id)
    cases = (await db.execute(select(FraudCase).where(where).order_by(*order)
        .offset((page - 1) * limit).limit(limit))).scalars().all()
    return CasesPage(items=[FraudCaseListItem.model_validate(case) for case in cases],
        total=total, page=page, limit=limit)


def _bulk_filter_values(values: dict) -> list:
    try:
        parsed = BulkFilters.model_validate({key: value for key, value in values.items() if value != ""})
        return _filters(**parsed.model_dump())
    except ValidationError as exc:
        raise HTTPException(422, "Invalid bulk selection filter") from exc


@router.post("/bulk-actions", response_model=BatchOut)
async def create_batch(body: BulkActionBody, request: Request,
                       db: AsyncSession = Depends(get_db), user: User = Depends(require_user)):
    action = body.action.upper()
    if action not in {"REVIEW", "RELEASED", "ESCALATED", "CONFIRMED", "DISMISSED", "APPROVE", "REJECT"}:
        raise HTTPException(400, "Unsupported bulk action")
    if action in {"APPROVE", "REJECT"}:
        if not role_has(user.role, "approve_case"):
            raise HTTPException(403, "Case approver access required")
    elif action == "ESCALATED" and not role_has(user.role, "act"):
        raise HTTPException(403, "Analyst/inputter access required")
    elif not (role_has(user.role, "act") or role_has(user.role, "approve_case")):
        raise HTTPException(403, "Case action access required")

    if body.all_matching:
        conditions = _bulk_filter_values(body.filters)
        where = and_(*conditions) if conditions else open_condition()
        ids = list((await db.execute(select(FraudCase.id).where(where).order_by(FraudCase.id)
            .limit(100_001))).scalars().all())
        if len(ids) > 100_000:
            raise HTTPException(422, "Bulk jobs are limited to 100,000 cases")
    else:
        ids = list(dict.fromkeys(body.case_ids))
    if not ids:
        raise HTTPException(422, "Select at least one case")

    batch = CaseBatch(action=action, case_ids=ids, rationale=body.rationale.strip(),
        requested_by=user.username, total=len(ids))
    db.add(batch)
    await db.commit()
    await db.refresh(batch)
    await audit.record(user.username, "CASE_BATCH_SUBMITTED", target=batch.id,
        detail=f"{action} for {len(ids)} case(s): {batch.rationale}", request=request)
    return BatchOut.model_validate(batch)


@router.get("/batches/{batch_id}", response_model=BatchOut)
async def get_batch(batch_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(require_user)):
    batch = await db.get(CaseBatch, batch_id)
    if not batch:
        raise HTTPException(404, "Batch not found")
    if batch.requested_by != user.username and not role_has(user.role, "approve_case"):
        raise HTTPException(403, "This batch belongs to another user")
    return BatchOut.model_validate(batch)


async def _load_case(db: AsyncSession, case_id: str) -> FraudCase:
    case = (await db.execute(select(FraudCase).where(FraudCase.id == case_id)
        .options(selectinload(FraudCase.actions), selectinload(FraudCase.decisions))
        .with_for_update())).scalar_one_or_none()
    if not case:
        raise HTTPException(404, "Case not found")
    return case


async def _result(db: AsyncSession, case_id: str) -> FraudCaseOut:
    case = (await db.execute(select(FraudCase).where(FraudCase.id == case_id)
        .options(selectinload(FraudCase.actions), selectinload(FraudCase.decisions))
        .execution_options(populate_existing=True))).scalar_one_or_none()
    if not case:
        raise HTTPException(404, "Case not found")
    return FraudCaseOut.model_validate(case)


@router.get("/{case_id}", response_model=FraudCaseOut)
async def get_case(case_id: str, db: AsyncSession = Depends(get_db)):
    return await _result(db, case_id)


@router.post("/{case_id}/actions", response_model=FraudCaseOut)
async def add_action(case_id: str, body: CaseActionCreate, request: Request,
                     db: AsyncSession = Depends(get_db), user: User = Depends(require_user)):
    case = await _load_case(db, case_id)
    await case_workflow.apply_action(db, case, user, body.action, body.note)
    await db.commit()
    await audit.record(user.username, f"CASE_{body.action.upper()}", target=case_id,
        detail=body.note, request=request)
    await broadcaster.broadcast({"event": "case_updated", "case_id": case_id})
    return await _result(db, case_id)


@router.post("/{case_id}/decision/approve", response_model=FraudCaseOut)
async def approve_decision(case_id: str, body: DecisionBody, request: Request,
                           db: AsyncSession = Depends(get_db), user: User = Depends(require_case_approver)):
    case = await _load_case(db, case_id)
    await case_workflow.decide(db, case, user, True, body.note)
    await db.commit()
    await audit.record(user.username, "CASE_DECISION_APPROVED", target=case_id,
        detail=body.note, request=request)
    await broadcaster.broadcast({"event": "case_updated", "case_id": case_id})
    return await _result(db, case_id)


@router.post("/{case_id}/decision/reject", response_model=FraudCaseOut)
async def reject_decision(case_id: str, body: DecisionBody, request: Request,
                          db: AsyncSession = Depends(get_db), user: User = Depends(require_case_approver)):
    case = await _load_case(db, case_id)
    await case_workflow.decide(db, case, user, False, body.note)
    await db.commit()
    await audit.record(user.username, "CASE_DECISION_REJECTED", target=case_id,
        detail=body.note, request=request)
    await broadcaster.broadcast({"event": "case_updated", "case_id": case_id})
    return await _result(db, case_id)


@router.post("/{case_id}/decision/cancel", response_model=FraudCaseOut)
async def cancel_decision(case_id: str, request: Request, db: AsyncSession = Depends(get_db),
                          user: User = Depends(require_user)):
    case = await _load_case(db, case_id)
    await case_workflow.cancel_proposal(db, case, user)
    await db.commit()
    await audit.record(user.username, "CASE_DECISION_CANCELLED", target=case_id, request=request)
    await broadcaster.broadcast({"event": "case_updated", "case_id": case_id})
    return await _result(db, case_id)
