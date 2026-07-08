"""Read-only aggregate endpoints powering the Customers, Rule Engine and Analytics pages."""
from datetime import datetime, date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import require_user
from backend.database import get_db
from backend.models import FraudCase, User
from backend.services import analyzer as A
from backend.services import sanctions as S

router = APIRouter(tags=["insights"])

OPEN_STATUSES = ("OPEN", "UNDER_REVIEW")


@router.get("/customers")
async def customers(
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_user),
):
    """Per-account rollup across all analyzed transactions."""
    rows = (await db.execute(
        select(
            FraudCase.account_id,
            func.count().label("txns"),
            func.sum(func.iif(FraudCase.status != "CLEAN", 1, 0)).label("flagged"),
            func.sum(func.iif(FraudCase.status.in_(OPEN_STATUSES), 1, 0)).label("open"),
            func.sum(func.iif(FraudCase.sanctions_hit == True, 1, 0)).label("sanctions"),  # noqa: E712
            func.sum(func.iif(FraudCase.sar_recommended == True, 1, 0)).label("sar"),        # noqa: E712
            func.max(FraudCase.risk_score).label("max_risk"),
            func.sum(FraudCase.amount).label("total_amount"),
            func.max(FraudCase.currency).label("currency"),
            func.max(FraudCase.created_at).label("last_activity"),
        )
        .group_by(FraudCase.account_id)
        .order_by(func.max(FraudCase.risk_score).desc())
        .limit(limit)
    )).all()

    return {
        "count": len(rows),
        "items": [
            {
                "account_id": r.account_id,
                "transactions": int(r.txns or 0),
                "flagged": int(r.flagged or 0),
                "open": int(r.open or 0),
                "sanctions_hits": int(r.sanctions or 0),
                "sar_count": int(r.sar or 0),
                "max_risk": r.max_risk,
                "total_amount": round(float(r.total_amount or 0), 2),
                "currency": r.currency,
                "last_activity": str(r.last_activity) if r.last_activity else None,
            }
            for r in rows
        ],
    }


@router.get("/analytics")
async def analytics(db: AsyncSession = Depends(get_db), _user: User = Depends(require_user)):
    """KPIs for the Analytics page — all computed from real case data."""
    today_start = datetime.combine(date.today(), datetime.min.time())

    async def count(*filters):
        stmt = select(func.count()).select_from(FraudCase)
        if filters:
            stmt = stmt.where(and_(*filters))
        return (await db.execute(stmt)).scalar_one()

    total = await count()
    flagged = await count(FraudCase.status != "CLEAN")
    open_cases = await count(FraudCase.status.in_(OPEN_STATUSES))
    alerts_today = await count(FraudCase.created_at >= today_start, FraudCase.status != "CLEAN")
    confirmed = await count(FraudCase.status == "CONFIRMED_FRAUD")
    dismissed = await count(FraudCase.status == "DISMISSED")
    resolved = confirmed + dismissed

    # Value flagged for review, per currency (mixed-currency safe).
    q = await db.execute(
        select(FraudCase.currency, func.sum(FraudCase.amount))
        .where(FraudCase.status != "CLEAN")
        .group_by(FraudCase.currency)
        .order_by(func.sum(FraudCase.amount).desc())
    )
    value_flagged = [{"currency": cur, "amount": round(float(total_amt or 0), 2)} for cur, total_amt in q.all()]

    # Top fraud types (flagged cases only).
    q = await db.execute(
        select(FraudCase.fraud_type, func.count())
        .where(FraudCase.fraud_type.isnot(None))
        .group_by(FraudCase.fraud_type)
        .order_by(func.count().desc())
    )
    top_fraud_types = [{"type": t, "count": c} for t, c in q.all()]

    return {
        "transactions_processed": total,
        "alerts_today": alerts_today,
        "open_cases": open_cases,
        "value_flagged": value_flagged,          # "Fraud Loss Prevented" — value surfaced for review
        "resolved": {"confirmed": confirmed, "dismissed": dismissed, "total": resolved},
        # False positive rate among REVIEWED (resolved) alerts; null until any are resolved.
        "false_positive_rate": (dismissed / resolved) if resolved else None,
        "top_fraud_types": top_fraud_types,
        "flagged_total": flagged,
    }


from pydantic import BaseModel


class ScreenRequest(BaseModel):
    names: list[str]


@router.post("/screening/check")
async def screening_check(body: ScreenRequest, _user: User = Depends(require_user)):
    """Batch-screen arbitrary names (e.g. your customer base) against the OFAC
    SDN list (+ configured PEP list). Returns only the hits."""
    if len(body.names) > 5000:
        return {"error": "Maximum 5,000 names per request"}
    hits = []
    for name in body.names:
        m = S.screen(name)
        if m:
            hits.append({
                "query": name, "matched_name": m.matched_name, "score": m.score,
                "list_type": m.list_type, "program": m.program, "source": m.source,
            })
    return {"screened": len(body.names), "hits": hits}


@router.get("/search")
async def search(q: str = Query(..., min_length=2, max_length=100),
                 db: AsyncSession = Depends(get_db),
                 _user: User = Depends(require_user)):
    """Global search across cases by account, counterparty, case id, or reference."""
    like = f"%{q}%"
    rows = (await db.execute(
        select(FraudCase)
        .where(
            FraudCase.account_id.like(like)
            | FraudCase.counterparty_name.like(like)
            | FraudCase.counterparty_account.like(like)
            | FraudCase.reference.like(like)
            | FraudCase.id.like(f"{q}%")
        )
        .order_by(FraudCase.created_at.desc())
        .limit(50)
    )).scalars().all()
    return {
        "query": q,
        "count": len(rows),
        "items": [
            {"id": c.id, "account_id": c.account_id, "amount": c.amount, "currency": c.currency,
             "direction": c.direction, "counterparty_name": c.counterparty_name,
             "fraud_type": c.fraud_type, "risk_score": c.risk_score, "status": c.status,
             "created_at": str(c.created_at)}
            for c in rows
        ],
    }


@router.get("/rules")
async def rules(_user: User = Depends(require_user)):
    """Transparent view of the detection engine's thresholds and scoring rules.
    Sourced from the analyzer so the page always reflects the live configuration."""
    return {
        "regulatory_thresholds": {
            "ctr_by_currency": A._CTR_THRESHOLDS,
            "sar_ratio_of_ctr": A.SAR_RATIO,
            "note": "CTR per FinCEN/BSA (USD $10,000). SAR threshold = CTR × ratio. "
                    "Structuring is reportable regardless of amount.",
        },
        "detection_parameters": {
            "structuring_band_ratio": A.STRUCTURING_BAND_RATIO,
            "rolling_window_days": A.ROLLING_WINDOW_DAYS,
            "smurfing_window_hours": A.SMURFING_WINDOW_HOURS,
        },
        "scoring_components": [
            {"name": "Behavioral deviation", "points": "0–35", "detail": "How far the amount sits from the account's own baseline (z-score bands)."},
            {"name": "High-value transfer", "points": "5–20", "detail": "Amount at/above the CTR threshold, scaled by how far above."},
            {"name": "Near-threshold amount", "points": "20", "detail": "Amount in the structuring band just below the reporting threshold."},
            {"name": "Velocity clustering", "points": "25", "detail": "Multiple sub-threshold transfers over the rolling window that together exceed it."},
            {"name": "Outward smurfing", "points": "20", "detail": "Same-counterparty same-day accumulation crossing the threshold."},
            {"name": "Multi-source smurfing", "points": "25", "detail": "3+ distinct senders in 48h whose combined inflow exceeds the threshold."},
            {"name": "New counterparty", "points": "6–12", "detail": "First transaction with this counterparty."},
            {"name": "Odd hours", "points": "8", "detail": "Transaction between 01:00 and 05:00."},
            {"name": "New channel", "points": "5", "detail": "Channel not previously used by the account."},
            {"name": "Same-day velocity", "points": "5–10", "detail": "Unusually many transactions on the same day."},
            {"name": "Batch/systematic payment", "points": "-20", "detail": "Payroll/batch reference or batch ID reduces suspicion."},
            {"name": "Established high-value pattern", "points": "-10", "detail": "Account with a consistent history of large transfers."},
        ],
        "risk_levels": [
            {"level": "LOW", "range": "0–30"},
            {"level": "MEDIUM", "range": "31–55"},
            {"level": "HIGH", "range": "56–75"},
            {"level": "CRITICAL", "range": "76–100"},
        ],
        "sanctions": {
            "list": "OFAC SDN (+ optional PEP list)",
            "match_threshold": f"{S.DEFAULT_THRESHOLD:.2f} name-similarity",
            "note": "A sanctions match overrides the behavioral score and forces a block/report case.",
        },
    }
