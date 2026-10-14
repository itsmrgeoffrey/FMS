"""Documented CTR exemptions require independent administrator approval."""
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import require_admin
from backend.database import get_db
from backend.models import AuditLog, CtrExemption, PendingApproval, User
from backend.services import dual_control

router = APIRouter(prefix="/ctr-exemptions", tags=["ctr-exemptions"], dependencies=[Depends(require_admin)])


class ExemptionIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    subject_id: str = Field(min_length=1, max_length=64)
    subject_name: str = Field(min_length=1, max_length=200)
    exemption_type: Literal["BANK", "GOVERNMENT", "GOVERNMENT_AUTHORITY", "LISTED_ENTITY",
        "LISTED_SUBSIDIARY", "NONLISTED_BUSINESS", "PAYROLL_CUSTOMER"]
    account_ids: list[str] = Field(min_length=1, max_length=5000)
    effective_from: date
    expires_on: date
    reviewed_on: date
    review_due: date
    eligibility_basis: str = Field(min_length=10, max_length=8000)
    evidence_reference: str = Field(min_length=3, max_length=255)
    designation_reference: str | None = Field(None, max_length=255)
    eligibility_verified: Literal[True]

    @field_validator("account_ids")
    @classmethod
    def accounts(cls, values):
        result = list(dict.fromkeys(value.strip() for value in values))
        if any(not value or len(value) > 64 for value in result):
            raise ValueError("Each covered account must have an ID of 1-64 characters")
        return result

    @model_validator(mode="after")
    def scope(self):
        if not self.effective_from <= self.expires_on <= self.review_due:
            raise ValueError("Effective date must precede expiry, which cannot exceed the review due date")
        if not self.reviewed_on < self.review_due <= self.reviewed_on + timedelta(days=365):
            raise ValueError("Review due date must be within 365 days of the recorded eligibility review")
        if self.reviewed_on > datetime.now(timezone.utc).date():
            raise ValueError("Eligibility cannot be reviewed in the future")
        if self.expires_on < datetime.now(timezone.utc).date():
            raise ValueError("An expired exemption cannot be activated")
        if self.exemption_type not in {"BANK", "GOVERNMENT", "GOVERNMENT_AUTHORITY"} and not self.designation_reference:
            raise ValueError("A recorded FinCEN designation reference is required for this exemption category")
        return self


class RevocationIn(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)

    @field_validator("reason")
    @classmethod
    def reason_required(cls, value):
        if len(value.strip()) < 3:
            raise ValueError("A revocation reason is required")
        return value.strip()


def exemption_out(record):
    result = {column.name: getattr(record, column.name) for column in CtrExemption.__table__.columns}
    for key, value in result.items():
        if isinstance(value, (date, datetime)):
            result[key] = value.isoformat()
    today = datetime.now(timezone.utc).date()
    result["evaluation_status"] = ("REVOKED" if record.status == "REVOKED" else
        "EXPIRED" if today > min(record.expires_on, record.review_due) else
        "SCHEDULED" if today < record.effective_from else "ACTIVE")
    return result


async def records_for(db, subject_ids):
    if not subject_ids:
        return []
    result = []
    subjects = sorted(subject_ids)
    for start in range(0, len(subjects), 500):
        records = (await db.execute(select(CtrExemption).where(
            CtrExemption.subject_id.in_(subjects[start:start + 500])).order_by(CtrExemption.approved_at.desc()))).scalars().all()
        result.extend(exemption_out(record) for record in records)
    return result


@router.get("")
async def list_exemptions(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(CtrExemption).order_by(CtrExemption.approved_at.desc()))).scalars().all()
    return {"items": [exemption_out(row) for row in rows]}


@router.post("")
async def propose(body: ExemptionIn, request: Request, db: AsyncSession = Depends(get_db),
                  admin: User = Depends(require_admin)):
    identifier = str(uuid.uuid4())
    return await dual_control.submit_or_execute(db, request, admin, "CTR_EXEMPTION_CREATE",
        {"id": identifier, "exemption": body.model_dump(mode="json")},
        f"CTR exemption for {body.subject_id}, {body.exemption_type}, "
        f"{len(body.account_ids)} accounts, {body.effective_from} to {body.expires_on}", target=identifier)


@router.post("/{identifier}/revoke")
async def revoke(identifier: str, body: RevocationIn, request: Request,
                 db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    record = await db.get(CtrExemption, identifier)
    if not record or record.status != "ACTIVE":
        raise HTTPException(409, "An active exemption record is required")
    return await dual_control.submit_or_execute(db, request, admin, "CTR_EXEMPTION_REVOKE",
        {"id": identifier, "reason": body.reason},
        f"Revoke CTR exemption for {record.subject_id}: {body.reason}"[:300], target=identifier)


async def _verify_approval(db, actor, approval):
    if not approval:
        raise HTTPException(403, "Independent approval is required")
    people = (await db.execute(select(User).where(User.username.in_((approval.requested_by, actor))))).scalars().all()
    if actor == approval.requested_by or len(people) != 2 or any(
            person.role != "admin" or not person.is_active for person in people):
        raise HTTPException(403, "Two different active administrators are required")
    decided = await db.execute(update(PendingApproval).where(PendingApproval.id == approval.id,
        PendingApproval.status == "pending").values(status="approved", decided_by=actor,
            decided_at=datetime.utcnow()))
    if decided.rowcount != 1:
        raise HTTPException(409, "This exemption proposal is no longer pending")


@dual_control.register("CTR_EXEMPTION_CREATE")
async def create_approved(db, payload, actor, request, *, approval=None):
    try:
        body = ExemptionIn.model_validate(payload["exemption"])
    except ValidationError as exc:
        raise HTTPException(409, "Exemption scope is no longer valid. Reject this proposal and submit current eligibility evidence and dates.") from exc
    await _verify_approval(db, actor, approval)
    if await db.get(CtrExemption, payload["id"]):
        raise HTTPException(409, "This exemption record already exists")
    values = body.model_dump(exclude={"eligibility_verified"})
    db.add(CtrExemption(id=payload["id"], **values, created_by=approval.requested_by, approved_by=actor))
    db.add(AuditLog(username=actor, action="CTR_EXEMPTION_APPROVED", target=payload["id"],
        detail=f"Maker {approval.requested_by}; {body.subject_id}; evidence {body.evidence_reference}"))
    await db.commit()
    return {"id": payload["id"], "status": "ACTIVE"}


@dual_control.register("CTR_EXEMPTION_REVOKE")
async def revoke_approved(db, payload, actor, request, *, approval=None):
    await _verify_approval(db, actor, approval)
    changed = await db.execute(update(CtrExemption).where(CtrExemption.id == payload["id"],
        CtrExemption.status == "ACTIVE").values(status="REVOKED", revoked_by=actor,
            revoked_at=datetime.utcnow(), revocation_reason=payload["reason"]))
    if changed.rowcount != 1:
        raise HTTPException(409, "This exemption is no longer active")
    db.add(AuditLog(username=actor, action="CTR_EXEMPTION_REVOKED", target=payload["id"], detail=payload["reason"]))
    await db.commit()
    return {"id": payload["id"], "status": "REVOKED"}
