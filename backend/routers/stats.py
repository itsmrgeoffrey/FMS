from datetime import datetime, date, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import require_user
from backend.database import get_db
from backend.models import FraudCase, User
from backend.schemas import StatsOut, HealthOut
from backend.services import poller

router = APIRouter(tags=["stats"])


@router.get("/stats", response_model=StatsOut)
async def get_stats(db: AsyncSession = Depends(get_db), _user: User = Depends(require_user)):
    today_start = datetime.combine(date.today(), datetime.min.time())

    async def count(filters):
        q = await db.execute(select(func.count()).select_from(FraudCase).where(and_(*filters)))
        return q.scalar_one()

    flagged_today = await count([FraudCase.created_at >= today_start])
    high_confidence = await count([FraudCase.confidence == "HIGH", FraudCase.status == "OPEN"])
    pending_review = await count([FraudCase.status.in_(["OPEN", "UNDER_REVIEW"])])
    confirmed = await count([FraudCase.status == "CONFIRMED_FRAUD"])
    dismissed_today = await count([
        FraudCase.status == "DISMISSED",
        FraudCase.updated_at >= today_start,
    ])

    return StatsOut(
        flagged_today=flagged_today,
        high_confidence=high_confidence,
        pending_review=pending_review,
        confirmed_fraud=confirmed,
        dismissed_today=dismissed_today,
    )


OPEN_STATUSES = ("OPEN", "UNDER_REVIEW")
ACTIVITY_DAYS = 14


@router.get("/stats/dashboard")
async def dashboard(db: AsyncSession = Depends(get_db), _user: User = Depends(require_user)):
    """Aggregates powering the overview dashboard. One round trip, all sections."""
    today_start = datetime.combine(date.today(), datetime.min.time())

    async def count(*filters):
        q = await db.execute(select(func.count()).select_from(FraudCase).where(and_(*filters)) if filters
                             else select(func.count()).select_from(FraudCase))
        return q.scalar_one()

    total_cases = await count()
    open_cases = await count(FraudCase.status.in_(OPEN_STATUSES))
    flagged_today = await count(FraudCase.created_at >= today_start, FraudCase.status != "CLEAN")
    confirmed = await count(FraudCase.status == "CONFIRMED_FRAUD")
    sanctions_hits = await count(FraudCase.sanctions_hit == True)  # noqa: E712
    ctr_required = await count(FraudCase.ctr_required == True)  # noqa: E712
    sar_open = await count(FraudCase.sar_recommended == True, FraudCase.status.in_(OPEN_STATUSES))  # noqa: E712

    # Soonest SAR filing deadline among open SAR-recommended cases (30-day clock).
    q = await db.execute(
        select(func.min(FraudCase.created_at))
        .where(FraudCase.sar_recommended == True, FraudCase.status.in_(OPEN_STATUSES))  # noqa: E712
    )
    oldest_sar = q.scalar_one_or_none()
    sar_soonest_days = None
    if oldest_sar:
        sar_soonest_days = ((oldest_sar + timedelta(days=30)).date() - datetime.utcnow().date()).days

    # Daily activity, last N days (flagged vs clean), zero-filled.
    cutoff = datetime.combine(date.today() - timedelta(days=ACTIVITY_DAYS - 1), datetime.min.time())
    q = await db.execute(
        select(
            func.date(FraudCase.created_at),
            func.sum(func.iif(FraudCase.status != "CLEAN", 1, 0)),
            func.sum(func.iif(FraudCase.status == "CLEAN", 1, 0)),
        )
        .where(FraudCase.created_at >= cutoff)
        .group_by(func.date(FraudCase.created_at))
    )
    by_day = {row[0]: {"flagged": int(row[1] or 0), "clean": int(row[2] or 0)} for row in q.all()}
    activity = []
    for i in range(ACTIVITY_DAYS):
        d = (date.today() - timedelta(days=ACTIVITY_DAYS - 1 - i)).isoformat()
        entry = by_day.get(d, {"flagged": 0, "clean": 0})
        activity.append({"date": d, **entry})

    # Fraud-type breakdown (flagged cases only).
    q = await db.execute(
        select(FraudCase.fraud_type, func.count())
        .where(FraudCase.fraud_type.isnot(None))
        .group_by(FraudCase.fraud_type)
        .order_by(func.count().desc())
    )
    fraud_types = [{"type": t, "count": c} for t, c in q.all()]

    # Risk-level distribution across all analyzed cases.
    def level_expr():
        return func.iif(FraudCase.risk_score <= 30, "LOW",
               func.iif(FraudCase.risk_score <= 55, "MEDIUM",
               func.iif(FraudCase.risk_score <= 75, "HIGH", "CRITICAL")))
    q = await db.execute(
        select(level_expr(), func.count())
        .where(FraudCase.risk_score.isnot(None))
        .group_by(level_expr())
    )
    risk_rows = dict(q.all())
    risk_levels = [{"level": lv, "count": int(risk_rows.get(lv, 0))} for lv in ("LOW", "MEDIUM", "HIGH", "CRITICAL")]

    # Amount currently under investigation, per currency.
    q = await db.execute(
        select(FraudCase.currency, func.sum(FraudCase.amount))
        .where(FraudCase.status.in_(OPEN_STATUSES))
        .group_by(FraudCase.currency)
        .order_by(func.sum(FraudCase.amount).desc())
    )
    amounts_open = [{"currency": cur, "total": round(float(total or 0), 2)} for cur, total in q.all()]

    # Highest-risk open cases needing attention.
    q = await db.execute(
        select(FraudCase)
        .where(FraudCase.status.in_(OPEN_STATUSES))
        .order_by(FraudCase.risk_score.desc(), FraudCase.created_at.desc())
        .limit(5)
    )
    attention = [
        {
            "id": c.id, "account_id": c.account_id, "amount": c.amount, "currency": c.currency,
            "direction": c.direction, "fraud_type": c.fraud_type, "risk_score": c.risk_score,
            "sanctions_hit": c.sanctions_hit, "sar_recommended": c.sar_recommended,
            "created_at": str(c.created_at),
        }
        for c in q.scalars().all()
    ]

    return {
        "totals": {
            "total_cases": total_cases,
            "open_cases": open_cases,
            "flagged_today": flagged_today,
            "confirmed_fraud": confirmed,
            "sanctions_hits": sanctions_hits,
            "ctr_required": ctr_required,
            "sar_open": sar_open,
            "sar_soonest_deadline_days": sar_soonest_days,
        },
        "activity": activity,
        "fraud_types": fraud_types,
        "risk_levels": risk_levels,
        "amounts_open": amounts_open,
        "attention": attention,
    }


@router.get("/health", response_model=HealthOut)
async def health(db: AsyncSession = Depends(get_db)):
    adapter = poller.get_adapter()
    bank_ok = await adapter.is_connected()
    running = poller.is_running()
    err = poller.last_error()
    return HealthOut(
        status="ok" if (running and bank_ok and not err) else "degraded",
        bank_db_connected=bank_ok,
        poller_running=running,
        last_poll_at=poller.last_poll_at(),
        last_error=err,
    )
