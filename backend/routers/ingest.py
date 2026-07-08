"""Push ingestion API.

For institutions that will not (or cannot) grant database access: their system
POSTs each transaction as it happens and receives the risk verdict
synchronously — detect-at-the-moment monitoring with no DB integration.

Auth is the machine API key (X-API-Key). Unlike the browser endpoints, this
REFUSES to run with no key configured — an open ingestion endpoint would let
anyone pollute the case queue.

History for behavioral baselines comes from FMS's own ingested-transactions
store, so push-mode institutions get the full engine (structuring, smurfing,
velocity, deviation) without exposing their database.
"""
import asyncio
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.adapters.base import NormalizedTransaction
from backend.config import bank_config, settings
from backend.database import get_db, SessionLocal
from backend.models import FraudCase, IngestedTransaction
from backend.services import analyzer, emailer, sanctions
from backend.services.broadcaster import broadcaster

log = logging.getLogger(__name__)
router = APIRouter(prefix="/ingest", tags=["ingest"])


async def require_ingest_key(x_api_key: str | None = Header(default=None)) -> None:
    key = (settings.fms_ingest_api_key or settings.fms_api_key).strip()
    if not key:
        raise HTTPException(status_code=503, detail="Ingestion disabled: set FMS_INGEST_API_KEY on the server first")
    if x_api_key != key:
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key")


class TxnIn(BaseModel):
    external_id: str = Field(..., max_length=128)   # caller's unique transaction id
    account_id: str = Field(..., max_length=64)
    amount: float = Field(..., gt=0)
    direction: str = Field(..., pattern="^(INWARD|OUTWARD)$")
    timestamp: datetime | None = None               # defaults to now (UTC)
    counterparty_account: str | None = Field(None, max_length=64)
    counterparty_name: str | None = Field(None, max_length=200)
    channel: str | None = Field(None, max_length=40)
    currency: str = Field("USD", max_length=10)
    reference: str | None = Field(None, max_length=255)
    account_holder_name: str | None = Field(None, max_length=200)  # screened against OFAC if given


def _to_normalized(t: IngestedTransaction) -> NormalizedTransaction:
    return NormalizedTransaction(
        id=t.external_id, account_id=t.account_id, amount=t.amount,
        direction=t.direction, timestamp=t.timestamp,
        counterparty_account=t.counterparty_account, counterparty_name=t.counterparty_name,
        channel=t.channel, currency=t.currency, reference=t.reference,
        status=None, source_table="api",
    )


@router.post("/transactions", dependencies=[Depends(require_ingest_key)])
async def ingest_transaction(body: TxnIn, db: AsyncSession = Depends(get_db)):
    ts = body.timestamp or datetime.utcnow()

    # Idempotency: same external_id -> return the existing verdict, don't re-case.
    existing = (await db.execute(
        select(FraudCase).where(FraudCase.source_table == "api",
                                FraudCase.source_txn_id == body.external_id)
    )).scalar_one_or_none()
    if existing:
        return _verdict(existing, duplicate=True)

    row = IngestedTransaction(
        external_id=body.external_id, account_id=body.account_id, amount=body.amount,
        direction=body.direction, timestamp=ts,
        counterparty_account=body.counterparty_account, counterparty_name=body.counterparty_name,
        channel=body.channel, currency=body.currency.upper(), reference=body.reference,
        account_holder_name=body.account_holder_name,
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="external_id already ingested")

    history_days = int(bank_config.get("monitoring", {}).get("history_days", 90))
    cutoff = ts - timedelta(days=history_days)
    hist_rows = (await db.execute(
        select(IngestedTransaction)
        .where(IngestedTransaction.account_id == body.account_id,
               IngestedTransaction.timestamp >= cutoff,
               IngestedTransaction.external_id != body.external_id)
        .order_by(IngestedTransaction.timestamp.desc())
    )).scalars().all()

    txn = _to_normalized(row)
    result = await analyzer.analyze(txn, [_to_normalized(h) for h in hist_rows])

    # Screen the ACCOUNT HOLDER too (the counterparty is screened inside analyze()).
    holder_hit = sanctions.screen(body.account_holder_name) if body.account_holder_name else None
    if holder_hit and holder_hit.list_type == "SDN":
        result.sanctions_hit = True
        detail = (f"Account holder '{body.account_holder_name}' matches {holder_hit.source} entry "
                  f"'{holder_hit.matched_name}' (program: {holder_hit.program or 'N/A'}, {holder_hit.score:.0%} match)")
        result.sanctions_detail = f"{result.sanctions_detail}; {detail}" if result.sanctions_detail else detail
        result.is_fraudulent, result.confidence, result.fraud_type = True, "HIGH", "sanctions match"
        result.reasons = [f"OFAC SANCTIONS MATCH — {detail}. Block or reject and report to OFAC."] + result.reasons

    case = FraudCase(
        source_table="api", source_txn_id=body.external_id, account_id=body.account_id,
        amount=body.amount, direction=body.direction, timestamp=ts,
        counterparty_account=body.counterparty_account, counterparty_name=body.counterparty_name,
        channel=body.channel, currency=body.currency.upper(), reference=body.reference,
        risk_score=result.risk_score, ctr_required=result.ctr_required, ctr_reason=result.ctr_reason,
        sar_recommended=result.sar_recommended, sar_reason=result.sar_reason,
        sanctions_hit=result.sanctions_hit, sanctions_detail=result.sanctions_detail,
        confidence=result.confidence, fraud_type=result.fraud_type,
        reasons=result.reasons, ai_summary=result.summary,
        status="OPEN" if result.is_fraudulent else "CLEAN",
    )
    async with SessionLocal() as wdb:
        wdb.add(case)
        try:
            await wdb.commit()
            await wdb.refresh(case)
        except IntegrityError:
            await wdb.rollback()
            raise HTTPException(status_code=409, detail="external_id already ingested")

    if result.is_fraudulent:
        payload = {
            "id": case.id, "account_id": case.account_id, "amount": case.amount,
            "currency": case.currency, "direction": case.direction,
            "confidence": case.confidence, "fraud_type": case.fraud_type,
            "counterparty_name": case.counterparty_name, "counterparty_account": case.counterparty_account,
            "channel": case.channel, "reasons": case.reasons, "ai_summary": case.ai_summary,
            "ctr_required": case.ctr_required, "sar_recommended": case.sar_recommended,
            "sanctions_hit": case.sanctions_hit, "sanctions_detail": case.sanctions_detail,
            "created_at": str(case.created_at),
        }
        await broadcaster.broadcast({"event": "new_case", "case": payload})
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, emailer.send_fraud_alert, payload)
        loop.run_in_executor(None, emailer.send_webhook_alert, payload)

    return _verdict(case)


def _verdict(case: FraudCase, duplicate: bool = False) -> dict:
    return {
        "case_id": case.id,
        "duplicate": duplicate,
        "flagged": case.status != "CLEAN",
        "risk_score": case.risk_score,
        "confidence": case.confidence,
        "fraud_type": case.fraud_type,
        "sanctions_hit": case.sanctions_hit,
        "ctr_required": case.ctr_required,
        "sar_recommended": case.sar_recommended,
        "reasons": case.reasons,
    }
