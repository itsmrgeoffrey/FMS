from datetime import datetime, date
from fastapi import APIRouter, Depends
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import FraudCase
from backend.schemas import StatsOut, HealthOut
from backend.services import poller

router = APIRouter(tags=["stats"])


@router.get("/stats", response_model=StatsOut)
async def get_stats(db: AsyncSession = Depends(get_db)):
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
