"""Authenticated entry points into the shared transaction processor."""
import hmac
from datetime import datetime, date
from typing import Literal
from decimal import Decimal
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession
from backend.adapters.base import NormalizedTransaction
from backend.auth import require_admin, require_simulation
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
    external_id: str = Field(..., min_length=1, max_length=128,
        description="Stable deployment-wide ID. For multiple senders use system-prefix:original-id (max 128 characters); keep it unchanged on retries. Channel does not namespace IDs.")
    account_id: str = Field(..., min_length=1, max_length=64)
    amount: Decimal = Field(..., gt=0, max_digits=24, decimal_places=6, allow_inf_nan=False)
    direction: str = Field(..., pattern="^(INWARD|OUTWARD)$")
    timestamp: datetime | None = None
    counterparty_account: str | None = Field(None, max_length=64)
    counterparty_name: str | None = Field(None, max_length=200)
    # Direction-aware convenience aliases. The normalized storage contract
    # remains counterparty_* so API, simulator, and database-poll sources use
    # one processor, but callers can name the party in business terms.
    beneficiary_account: str | None = Field(None, max_length=64)
    beneficiary_name: str | None = Field(None, max_length=200)
    sender_account: str | None = Field(None, max_length=64)
    sender_name: str | None = Field(None, max_length=200)
    channel: str | None = Field(None, max_length=40)
    currency: str = Field("USD", pattern="^[A-Za-z]{3}$")
    reference: str | None = Field(None, max_length=255)
    account_holder_name: str | None = Field(None, max_length=200)
    account_holder_id: str | None = Field(None, max_length=64)
    account_open_date: date | None = None
    is_cash: bool | None = None
    business_date: date | None = None
    transaction_instrument: str | None = Field(None, max_length=40)
    branch_id: str | None = Field(None, max_length=64)
    location_id: str | None = Field(None, max_length=64)
    conductor_id: str | None = Field(None, max_length=64)
    conductor_name: str | None = Field(None, max_length=200)
    acting_as_agent: bool | None = None
    cash_purpose: Literal["PAYROLL", "OTHER"] | None = None

    @field_validator("external_id", "account_id")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Identifier must not be blank")
        return value.strip()

    @model_validator(mode="after")
    def normalize_directional_party(self):
        """Keep beneficiary/sender semantics aligned to the declared direction.

        FMS must not guess direction from a party name: direction drives cash
        reporting, behavioral checks, and the presentation of the party. The
        source-specific aliases make API integrations clearer while preventing
        a sender from being silently recorded as an outward beneficiary.
        """
        if self.direction == "OUTWARD":
            role, wrong_role = "beneficiary", "sender"
            named_account, named_name = self.beneficiary_account, self.beneficiary_name
            wrong_account, wrong_name = self.sender_account, self.sender_name
        else:
            role, wrong_role = "sender", "beneficiary"
            named_account, named_name = self.sender_account, self.sender_name
            wrong_account, wrong_name = self.beneficiary_account, self.beneficiary_name

        if wrong_account or wrong_name:
            raise ValueError(
                f"{wrong_role}_account and {wrong_role}_name do not apply to a {self.direction} transaction; "
                f"use {role}_account and {role}_name instead"
            )
        if self.counterparty_account and named_account and self.counterparty_account != named_account:
            raise ValueError("counterparty_account conflicts with the direction-specific account")
        if self.counterparty_name and named_name and self.counterparty_name != named_name:
            raise ValueError("counterparty_name conflicts with the direction-specific name")
        self.counterparty_account = self.counterparty_account or named_account
        self.counterparty_name = self.counterparty_name or named_name
        return self


def _to_normalized(row):
    return processing.from_row(row)


async def run_ingest(body: TxnIn, db: AsyncSession) -> dict:
    txn = NormalizedTransaction(id=body.external_id, account_id=body.account_id,
        amount=body.amount, direction=body.direction, timestamp=body.timestamp or datetime.utcnow(),
        counterparty_account=body.counterparty_account, counterparty_name=body.counterparty_name,
        account_holder_name=body.account_holder_name, account_holder_id=body.account_holder_id,
        account_open_date=body.account_open_date.isoformat() if body.account_open_date else None,
        channel=body.channel, currency=body.currency,
        reference=body.reference, status=None, source_table="api", is_cash=body.is_cash,
        business_date=body.business_date.isoformat() if body.business_date else None,
        transaction_instrument=body.transaction_instrument, branch_id=body.branch_id,
        location_id=body.location_id, conductor_id=body.conductor_id,
        conductor_name=body.conductor_name, acting_as_agent=body.acting_as_agent,
        cash_purpose=body.cash_purpose)
    return await processing.process(txn, timestamp_supplied=body.timestamp is not None)


@router.post("/transactions", dependencies=[Depends(require_ingest_key)])
async def ingest_transaction(body: TxnIn, db: AsyncSession = Depends(get_db)):
    return await run_ingest(body, db)


@router.post("/simulate")
async def simulate(body: TxnIn, db: AsyncSession = Depends(get_db),
                   user: User = Depends(require_simulation)):
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
