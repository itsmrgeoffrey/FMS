"""Authenticated entry points into the shared transaction processor."""
import hmac
from datetime import datetime, date
from decimal import Decimal
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from backend.adapters.base import NormalizedTransaction
from backend.auth import require_case_action, require_admin
from backend.config import settings
from backend.database import get_db
from backend.models import User, TransactionProcessing, NotificationDelivery
from sqlalchemy import select
from backend.routers import audit
from backend.services import processing

router = APIRouter(prefix="/ingest", tags=["ingest"])


async def require_ingest_key(request: Request, x_api_key: str | None = Header(default=None)):
    key = (settings.fms_ingest_api_key or settings.fms_api_key).strip()
    if not key:
        raise HTTPException(503, "Ingestion disabled: configure an ingestion API key")
    if not hmac.compare_digest((x_api_key or "").encode(), key.encode()):
        await audit.record("api-client", "INGEST_KEY_REJECTED", detail="Missing or invalid key", request=request)
        raise HTTPException(401, "Missing or invalid X-API-Key")


class TxnIn(BaseModel):
    external_id: str = Field(..., min_length=1, max_length=128)
    account_id: str = Field(..., min_length=1, max_length=64)
    amount: Decimal = Field(..., gt=0, max_digits=24, decimal_places=6, allow_inf_nan=False)
    direction: str = Field(..., pattern="^(INWARD|OUTWARD)$")
    timestamp: datetime | None = None
    counterparty_account: str | None = Field(None, max_length=64)
    counterparty_name: str | None = Field(None, max_length=200)
    channel: str | None = Field(None, max_length=40)
    currency: str = Field("USD", pattern="^[A-Za-z]{3}$")
    reference: str | None = Field(None, max_length=255)
    account_holder_name: str | None = Field(None, max_length=200)
    is_cash: bool | None = None
    business_date: date | None = None

    @field_validator("external_id", "account_id")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Identifier must not be blank")
        return value.strip()


def _to_normalized(row):
    return processing.from_row(row)


async def run_ingest(body: TxnIn, db: AsyncSession) -> dict:
    txn = NormalizedTransaction(id=body.external_id, account_id=body.account_id,
        amount=body.amount, direction=body.direction, timestamp=body.timestamp or datetime.utcnow(),
        counterparty_account=body.counterparty_account, counterparty_name=body.counterparty_name,
        account_holder_name=body.account_holder_name, channel=body.channel, currency=body.currency,
        reference=body.reference, status=None, source_table="api", is_cash=body.is_cash,
        business_date=body.business_date.isoformat() if body.business_date else None)
    return await processing.process(txn, timestamp_supplied=body.timestamp is not None)


@router.post("/transactions", dependencies=[Depends(require_ingest_key)])
async def ingest_transaction(body: TxnIn, db: AsyncSession = Depends(get_db)):
    return await run_ingest(body, db)


@router.post("/simulate")
async def simulate(body: TxnIn, db: AsyncSession = Depends(get_db),
                   user: User = Depends(require_case_action)):
    return await run_ingest(body, db)


@router.get("/processing", dependencies=[Depends(require_admin)])
async def processing_status(db: AsyncSession = Depends(get_db)):
    failures = (await db.execute(select(TransactionProcessing).where(
        TransactionProcessing.state != "COMPLETED").order_by(TransactionProcessing.updated_at).limit(100))).scalars().all()
    deliveries = (await db.execute(select(NotificationDelivery).where(
        NotificationDelivery.delivered == False).limit(100))).scalars().all()
    return {"transactions": [{"id": r.id, "external_id": r.source_txn_id, "source": r.source_table,
        "state": r.state, "attempts": r.attempts, "error": r.error} for r in failures],
        "notifications": [{"id": r.id, "channel": r.channel, "attempts": r.attempts,
        "error": r.error, "next_attempt_at": r.next_attempt_at} for r in deliveries]}


@router.post("/processing/{record_id}/retry", dependencies=[Depends(require_admin)])
async def retry_processing(record_id: str, db: AsyncSession = Depends(get_db)):
    record = await db.get(TransactionProcessing, record_id)
    if not record:
        raise HTTPException(404, "Processing record not found")
    if record.source_table != "api":
        raise HTTPException(409, "Database transactions retry through their poller with bank history")
    return await processing.process(processing.deserialize(record.payload))
