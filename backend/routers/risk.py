"""Institutional ML/TF risk assessment.

FinCEN's 2026 AML/CFT Program rule proposal would require every institution to
maintain a documented risk assessment that considers (1) the National AML/CFT
Priorities, (2) the institution's own ML/TF risks across products, services,
customers, channels, and geographies, and (3) the reports it files. This module
is that artifact, versioned:

  * a category grid the officer rates (inherent risk → controls → residual),
  * the eight National Priorities as a checklist pre-mapped to FMS detection
    coverage,
  * an activity snapshot auto-populated from FMS's own case/report data (the
    "reports filed" consideration),
  * draft → finalize flow with named actors and full audit entries.

Honesty boundary: FMS structures the assessment and brings the data. Every
RATING is the institution's judgment — the tool never auto-rates, because a
risk assessment an examiner will accept is the officer's assessment, not a
vendor's default.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import require_admin, require_user
from backend.database import get_db
from backend.models import FraudCase, IngestedTransaction, RiskAssessment, User
from backend.routers import audit
from backend.routers.insights import NATIONAL_PRIORITIES

router = APIRouter(prefix="/risk-assessment", tags=["risk-assessment"])

# Starter grid for a small US institution — rows are prompts, not conclusions.
# The officer edits, adds, and rates; FMS pre-fills nothing but the structure.
_DEFAULT_CATEGORIES: list[dict] = [
    {"area": "Products & services", "item": "Cash / currency services", "inherent": "", "controls": "", "residual": "", "notes": ""},
    {"area": "Products & services", "item": "Domestic wires and ACH", "inherent": "", "controls": "", "residual": "", "notes": ""},
    {"area": "Products & services", "item": "International transfers", "inherent": "", "controls": "", "residual": "", "notes": ""},
    {"area": "Products & services", "item": "Remote / API-originated payments", "inherent": "", "controls": "", "residual": "", "notes": ""},
    {"area": "Customers & entities", "item": "Cash-intensive businesses", "inherent": "", "controls": "", "residual": "", "notes": ""},
    {"area": "Customers & entities", "item": "Money services businesses (MSBs)", "inherent": "", "controls": "", "residual": "", "notes": ""},
    {"area": "Customers & entities", "item": "PEP-linked relationships", "inherent": "", "controls": "", "residual": "", "notes": ""},
    {"area": "Customers & entities", "item": "Non-resident / foreign customers", "inherent": "", "controls": "", "residual": "", "notes": ""},
    {"area": "Geographies", "item": "Local market footprint", "inherent": "", "controls": "", "residual": "", "notes": ""},
    {"area": "Geographies", "item": "HIFCA / HIDTA exposure", "inherent": "", "controls": "", "residual": "", "notes": ""},
    {"area": "Geographies", "item": "Foreign corridors served", "inherent": "", "controls": "", "residual": "", "notes": ""},
    {"area": "Channels", "item": "In-person / branch", "inherent": "", "controls": "", "residual": "", "notes": ""},
    {"area": "Channels", "item": "Online / mobile", "inherent": "", "controls": "", "residual": "", "notes": ""},
    {"area": "Channels", "item": "Third-party / partner-originated (API)", "inherent": "", "controls": "", "residual": "", "notes": ""},
]

_RATINGS = {"", "LOW", "MODERATE", "HIGH"}


def _default_priorities() -> list[dict]:
    return [
        {
            "priority": p["priority"],
            "fms_coverage": p["coverage"],
            "fms_how": p["how"],
            "applicable": None,      # the institution's call, not FMS's
            "notes": "",
        }
        for p in NATIONAL_PRIORITIES
    ]


async def _activity_snapshot(db: AsyncSession) -> dict:
    """The 'reports filed by the institution' consideration, from FMS's own
    records. Point-in-time; regenerated whenever a new draft is created."""
    async def count(*filters):
        stmt = select(func.count()).select_from(FraudCase)
        for f in filters:
            stmt = stmt.where(f)
        return (await db.execute(stmt)).scalar_one()

    total = await count()
    flagged = await count(FraudCase.status != "CLEAN")
    sar = await count(FraudCase.sar_recommended == True)          # noqa: E712
    ctr = await count(FraudCase.ctr_required == True)             # noqa: E712
    sanctions = await count(FraudCase.sanctions_hit == True)      # noqa: E712
    confirmed = await count(FraudCase.status == "CONFIRMED_FRAUD")
    dismissed = await count(FraudCase.status == "DISMISSED")

    typology_rows = (await db.execute(
        select(FraudCase.fraud_type, func.count())
        .where(FraudCase.fraud_type.isnot(None))
        .group_by(FraudCase.fraud_type)
        .order_by(func.count().desc())
        .limit(5)
    )).all()

    accounts = (await db.execute(
        select(func.count(func.distinct(FraudCase.account_id)))
    )).scalar_one()
    ingested = (await db.execute(
        select(func.count()).select_from(IngestedTransaction)
    )).scalar_one()
    date_range = (await db.execute(
        select(func.min(FraudCase.created_at), func.max(FraudCase.created_at))
    )).one()

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "cases_total": total,
        "cases_flagged": flagged,
        "sar_recommended": sar,
        "ctr_required": ctr,
        "sanctions_hits": sanctions,
        "resolved": {"confirmed": confirmed, "dismissed": dismissed},
        "top_typologies": [{"type": t, "count": c} for t, c in typology_rows],
        "distinct_accounts_seen": accounts,
        "ingested_transactions": ingested,
        "activity_window": {
            "from": str(date_range[0]) if date_range[0] else None,
            "to": str(date_range[1]) if date_range[1] else None,
        },
    }


def _meta(ra: RiskAssessment) -> dict:
    return {
        "id": ra.id, "version": ra.version, "status": ra.status, "title": ra.title,
        "overall_rating": ra.overall_rating,
        "created_by": ra.created_by, "created_at": str(ra.created_at),
        "updated_at": str(ra.updated_at),
        "finalized_by": ra.finalized_by,
        "finalized_at": str(ra.finalized_at) if ra.finalized_at else None,
    }


def _full(ra: RiskAssessment) -> dict:
    return {
        **_meta(ra),
        "categories": ra.categories,
        "priorities": ra.priorities,
        "activity_snapshot": ra.activity_snapshot,
        "summary": ra.summary,
    }


class AssessmentUpdate(BaseModel):
    title: str | None = None
    categories: list[dict] | None = None
    priorities: list[dict] | None = None
    overall_rating: str | None = None
    summary: str | None = None


def _validate_ratings(rows: list[dict]) -> None:
    for row in rows:
        for key in ("inherent", "residual"):
            if str(row.get(key, "") or "").upper() not in _RATINGS:
                raise HTTPException(422, f"Invalid rating {row.get(key)!r} — use LOW, MODERATE, HIGH, or leave blank.")


@router.get("")
async def list_assessments(db: AsyncSession = Depends(get_db), _user: User = Depends(require_user)):
    rows = (await db.execute(
        select(RiskAssessment).order_by(RiskAssessment.version.desc())
    )).scalars().all()
    return {
        "count": len(rows),
        "latest": _full(rows[0]) if rows else None,
        "versions": [_meta(r) for r in rows],
    }


@router.post("")
async def create_draft(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    """Start a new draft: carries forward the newest version's content (so an
    annual refresh edits last year's answers instead of a blank page) with a
    fresh activity snapshot."""
    newest = (await db.execute(
        select(RiskAssessment).order_by(RiskAssessment.version.desc()).limit(1)
    )).scalars().first()
    if newest and newest.status == "DRAFT":
        raise HTTPException(409, "A draft already exists — edit or finalize it first.")

    ra = RiskAssessment(
        version=(newest.version + 1) if newest else 1,
        status="DRAFT",
        title=newest.title if newest else "Institutional ML/TF Risk Assessment",
        categories=list(newest.categories) if newest else list(_DEFAULT_CATEGORIES),
        priorities=list(newest.priorities) if newest else _default_priorities(),
        activity_snapshot=await _activity_snapshot(db),
        overall_rating=None,
        summary=newest.summary if newest else None,
        created_by=admin.username,
    )
    db.add(ra)
    await db.commit()
    await db.refresh(ra)
    await audit.record(admin.username, "RISK_ASSESSMENT_DRAFTED", target=f"v{ra.version}")
    return _full(ra)


@router.get("/{assessment_id}")
async def get_assessment(assessment_id: str, db: AsyncSession = Depends(get_db),
                         _user: User = Depends(require_user)):
    ra = await db.get(RiskAssessment, assessment_id)
    if not ra:
        raise HTTPException(404, "Assessment not found")
    return _full(ra)


@router.put("/{assessment_id}")
async def update_assessment(assessment_id: str, body: AssessmentUpdate,
                            db: AsyncSession = Depends(get_db),
                            admin: User = Depends(require_admin)):
    ra = await db.get(RiskAssessment, assessment_id)
    if not ra:
        raise HTTPException(404, "Assessment not found")
    if ra.status == "FINAL":
        raise HTTPException(409, "This version is finalized — start a new draft to make changes.")

    if body.categories is not None:
        _validate_ratings(body.categories)
        ra.categories = body.categories
    if body.priorities is not None:
        ra.priorities = body.priorities
    if body.title is not None:
        ra.title = body.title.strip() or ra.title
    if body.overall_rating is not None:
        if body.overall_rating.upper() not in _RATINGS:
            raise HTTPException(422, "overall_rating must be LOW, MODERATE, HIGH, or blank.")
        ra.overall_rating = body.overall_rating.upper() or None
    if body.summary is not None:
        ra.summary = body.summary

    ra.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(ra)
    await audit.record(admin.username, "RISK_ASSESSMENT_UPDATED", target=f"v{ra.version}")
    return _full(ra)


@router.post("/{assessment_id}/refresh-snapshot")
async def refresh_snapshot(assessment_id: str, db: AsyncSession = Depends(get_db),
                           admin: User = Depends(require_admin)):
    ra = await db.get(RiskAssessment, assessment_id)
    if not ra:
        raise HTTPException(404, "Assessment not found")
    if ra.status == "FINAL":
        raise HTTPException(409, "This version is finalized — its snapshot is part of the record.")
    ra.activity_snapshot = await _activity_snapshot(db)
    ra.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(ra)
    return _full(ra)


@router.post("/{assessment_id}/finalize")
async def finalize_assessment(assessment_id: str, db: AsyncSession = Depends(get_db),
                              admin: User = Depends(require_admin)):
    """Freeze this version as the institution's assessment of record. The named
    admin who finalizes is recorded — an examiner-facing document needs an
    accountable owner, not a system signature."""
    ra = await db.get(RiskAssessment, assessment_id)
    if not ra:
        raise HTTPException(404, "Assessment not found")
    if ra.status == "FINAL":
        raise HTTPException(409, "Already finalized.")
    ra.status = "FINAL"
    ra.finalized_by = admin.username
    ra.finalized_at = datetime.utcnow()
    ra.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(ra)
    await audit.record(admin.username, "RISK_ASSESSMENT_FINALIZED", target=f"v{ra.version}")
    return _full(ra)
