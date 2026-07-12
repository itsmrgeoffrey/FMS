from datetime import datetime, date, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy import select, func, and_, cast, Date, case
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
    # Day bucketing is dialect-specific: SQLite's CAST(.. AS DATE) yields an
    # integer (numeric affinity), so use date() there; server DBs use a real
    # CAST. The key is normalized to an ISO date string either way.
    from backend.database import engine
    if engine.dialect.name == "sqlite":
        day = func.date(FraudCase.created_at)
    else:
        day = cast(FraudCase.created_at, Date)
    q = await db.execute(
        select(
            day,
            func.sum(case((FraudCase.status != "CLEAN", 1), else_=0)),
            func.sum(case((FraudCase.status == "CLEAN", 1), else_=0)),
        )
        .where(FraudCase.created_at >= cutoff)
        .group_by(day)
    )
    by_day = {str(row[0])[:10]: {"flagged": int(row[1] or 0), "clean": int(row[2] or 0)} for row in q.all()}
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

    # Risk-level distribution — counted per band (portable; avoids GROUP BY on a
    # computed CASE/IIF expression, which SQL Server rejects).
    low = await count(FraudCase.risk_score.isnot(None), FraudCase.risk_score <= 30)
    medium = await count(FraudCase.risk_score > 30, FraudCase.risk_score <= 55)
    high = await count(FraudCase.risk_score > 55, FraudCase.risk_score <= 75)
    critical = await count(FraudCase.risk_score > 75)
    risk_levels = [
        {"level": "LOW", "count": low}, {"level": "MEDIUM", "count": medium},
        {"level": "HIGH", "count": high}, {"level": "CRITICAL", "count": critical},
    ]

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
async def health(db: AsyncSession = Depends(get_db), _user: User = Depends(require_user)):
    from backend.config import bank_config
    api_mode = (bank_config.get("monitoring", {}) or {}).get("mode", "poll") == "api"
    bank_ok = False if api_mode else await poller.get_adapter().is_connected()
    running = poller.is_running()
    err = poller.last_error()
    healthy = running and not err and (api_mode or bank_ok)
    return HealthOut(
        status="ok" if healthy else "degraded",
        bank_db_connected=bank_ok,
        poller_running=running,
        last_poll_at=poller.last_poll_at(),
        last_error=err,
    )
