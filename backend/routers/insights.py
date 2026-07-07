"""Read-only aggregate endpoints powering the Customers and Rule Engine pages."""
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
