"""Shared, resumable transaction processing for the supported single-worker deployment."""
import asyncio
import logging
from dataclasses import asdict
from contextlib import asynccontextmanager, AsyncExitStack
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select

from backend.adapters.base import NormalizedTransaction
from backend.database import SessionLocal
from backend.models import FraudCase, IngestedTransaction, TransactionProcessing, AuditLog
from backend.config import bank_config
from backend.services import analyzer
from backend.services.broadcaster import broadcaster
from backend.services.delivery import enqueue

log = logging.getLogger(__name__)
# A bounded set of account locks prevents simultaneous same-account submissions
# observing incomplete histories, without retaining an unbounded lock dictionary.
_locks = [asyncio.Lock() for _ in range(256)]


def serialize(txn):
    value = asdict(txn)
    value["amount"] = format(txn.amount.normalize(), "f")
    value["timestamp"] = txn.timestamp.isoformat()
    return value


def deserialize(value):
    return NormalizedTransaction(**{**value, "timestamp": datetime.fromisoformat(value["timestamp"])})


def from_row(row):
    return NormalizedTransaction(
        id=getattr(row, "external_id", None) or row.source_txn_id,
        account_id=row.account_id, amount=row.amount, direction=row.direction,
        timestamp=row.timestamp, counterparty_account=row.counterparty_account,
        counterparty_name=row.counterparty_name, channel=row.channel,
        currency=row.currency, reference=row.reference, status=None,
        source_table=getattr(row, "source_table", "api"),
        account_holder_name=getattr(row, "account_holder_name", None),
    )


def verdict(case, assessment=None, duplicate=False):
    return {"case_id": case.id, "duplicate": duplicate, "processing_status": "COMPLETED",
            "flagged": case.status != "CLEAN" or case.ctr_required or case.sar_recommended or case.sanctions_hit,
            "review_status": case.status,
            "risk_score": case.risk_score, "confidence": case.confidence,
            "fraud_type": case.fraud_type, "sanctions_hit": case.sanctions_hit,
            "ctr_required": case.ctr_required, "sar_recommended": case.sar_recommended,
            "reasons": case.reasons, "assessment": assessment or {"version": "legacy", "regulatory_status": "REASSESSMENT_REQUIRED"}}


@asynccontextmanager
async def transaction_lock(txn):
    indices = sorted({hash(txn.account_id) % len(_locks), hash((txn.source_table, txn.id)) % len(_locks)})
    async with AsyncExitStack() as stack:
        for index in indices:
            await stack.enter_async_context(_locks[index])
        yield


async def process(txn, supplied_history=(), timestamp_supplied=True):
    async with transaction_lock(txn):
        async with SessionLocal() as db:
            record = (await db.execute(select(TransactionProcessing).where(
                TransactionProcessing.source_table == txn.source_table,
                TransactionProcessing.source_txn_id == txn.id))).scalar_one_or_none()
            existing = (await db.execute(select(FraudCase).where(
                FraudCase.source_table == txn.source_table, FraudCase.source_txn_id == txn.id))).scalar_one_or_none()
            if record:
                if not timestamp_supplied:
                    txn.timestamp = datetime.fromisoformat(record.payload["timestamp"])
                if serialize(txn) != record.payload:
                    raise HTTPException(409, "Transaction ID already belongs to a different payload")
            elif existing:
                previous = from_row(existing)
                if not timestamp_supplied:
                    txn.timestamp = previous.timestamp
                keys = ("account_id", "amount", "currency", "direction", "timestamp", "counterparty_account", "counterparty_name", "channel", "reference")
                if any(getattr(txn, k) != getattr(previous, k) for k in keys):
                    raise HTTPException(409, "Transaction ID already belongs to a different payload")
                return verdict(existing, duplicate=True)
            else:
                if txn.source_table == "api":
                    orphan = (await db.execute(select(IngestedTransaction).where(
                        IngestedTransaction.external_id == txn.id))).scalar_one_or_none()
                    if orphan:
                        previous = from_row(orphan)
                        if not timestamp_supplied:
                            txn.timestamp = previous.timestamp
                        keys = ("account_id", "amount", "currency", "direction", "timestamp", "counterparty_account", "counterparty_name", "channel", "reference", "account_holder_name")
                        if any(getattr(txn, k) != getattr(previous, k) for k in keys):
                            raise HTTPException(409, "Transaction ID already belongs to a different payload")
                record = TransactionProcessing(source_table=txn.source_table, source_txn_id=txn.id,
                    account_id=txn.account_id, payload=serialize(txn))
                db.add(record)
            if existing:
                return verdict(existing, record.assessment, duplicate=True)
            record.attempts = (record.attempts or 0) + 1
            record.state, record.error, record.updated_at = "PENDING", None, datetime.utcnow()
            await db.commit()
            record_id = record.id

        try:
            async with SessionLocal() as db:
                later = (await db.execute(select(FraudCase.id).where(FraudCase.account_id == txn.account_id,
                    FraudCase.timestamp > txn.timestamp).limit(1))).first() is not None
                history = {(h.source_table, h.id): h for h in supplied_history}
                history_days = int(bank_config.get("monitoring", {}).get("history_days", 90))
                # Include legacy API rows and cases, then prefer exact processing snapshots.
                for cls in (IngestedTransaction, FraudCase):
                    rows = (await db.execute(select(cls).where(cls.account_id == txn.account_id,
                        cls.timestamp <= txn.timestamp,
                        cls.timestamp >= txn.timestamp - timedelta(days=history_days)))).scalars().all()
                    for row in rows:
                        h = from_row(row)
                        history.setdefault((h.source_table, h.id), h)
                records = (await db.execute(select(TransactionProcessing).where(
                    TransactionProcessing.account_id == txn.account_id,
                    TransactionProcessing.state == "COMPLETED"))).scalars().all()
                for r in records:
                    h = deserialize(r.payload)
                    history[(h.source_table, h.id)] = h
            result = await analyzer.analyze(txn, list(history.values()))
            if later:
                result.regulatory_review = True
                result.reasons.insert(0, "Late-arriving transaction: review affected daily totals and subsequent assessments; later activity was excluded from this historical risk score.")
            screening_review = result.screening_status != "NO_MATCH"
            needs_review = result.is_fraudulent or result.ctr_required or result.sar_recommended or result.regulatory_review or screening_review
            assessment = {
                "version": "2", "detection_status": "SUSPICIOUS" if result.is_fraudulent else "NO_FRAUD_SIGNAL",
                "screening_status": result.screening_status, "screening_matches": result.screening_matches or [],
                "regulatory_status": "MANUAL_REVIEW" if result.regulatory_review else ("REVIEW_REQUIRED" if result.ctr_required or result.sar_recommended else "NO_TRIGGER"),
                "reporting_status": "NOT_FILED" if result.ctr_required or result.sar_recommended else "NOT_ASSESSED",
                "rules": result.assessed_rules, "cash_classification": txn.is_cash,
                "business_date": analyzer.business_day(txn),
                "late_arrival": later,
            }
            case = FraudCase(source_table=txn.source_table, source_txn_id=txn.id,
                account_id=txn.account_id, amount=float(txn.amount), direction=txn.direction,
                timestamp=txn.timestamp, counterparty_account=txn.counterparty_account,
                counterparty_name=txn.counterparty_name, channel=txn.channel, currency=txn.currency,
                reference=txn.reference, risk_score=result.risk_score, confidence=result.confidence,
                fraud_type=result.fraud_type, reasons=result.reasons, ai_summary=result.summary,
                ctr_required=result.ctr_required, ctr_reason=result.ctr_reason,
                sar_recommended=result.sar_recommended, sar_reason=result.sar_reason,
                sanctions_hit=result.sanctions_hit, sanctions_detail=result.sanctions_detail,
                status="OPEN" if needs_review else "CLEAN")
            async with SessionLocal() as db:
                db.add(case)
                await db.flush()
                record = await db.get(TransactionProcessing, record_id)
                record.state, record.case_id, record.assessment = "COMPLETED", case.id, assessment
                record.updated_at = datetime.utcnow()
                if txn.source_table == "api":
                    raw = (await db.execute(select(IngestedTransaction).where(IngestedTransaction.external_id == txn.id))).scalar_one_or_none()
                    if not raw:
                        db.add(IngestedTransaction(external_id=txn.id, account_id=txn.account_id,
                            amount=float(txn.amount), direction=txn.direction, timestamp=txn.timestamp,
                            counterparty_account=txn.counterparty_account, counterparty_name=txn.counterparty_name,
                            channel=txn.channel, currency=txn.currency, reference=txn.reference,
                            account_holder_name=txn.account_holder_name))
                payload = {**verdict(case, assessment), "id": case.id, "account_id": case.account_id,
                    "amount": case.amount, "currency": case.currency, "direction": case.direction,
                    "channel": case.channel, "counterparty_name": case.counterparty_name,
                    "counterparty_account": case.counterparty_account, "sanctions_detail": case.sanctions_detail,
                    "ai_summary": case.ai_summary, "created_at": str(case.created_at),
                    "source_table": txn.source_table, "external_id": txn.id, "status": case.status}
                if needs_review:
                    enqueue(db, "case.flagged", payload)
                if result.screening_matches:
                    db.add(AuditLog(username="system", action="SANCTIONS_HIT", target=case.id,
                        detail=f"Possible name matches: {len(result.screening_matches)}; identity verification required"))
                await db.commit()
            if needs_review:
                await broadcaster.broadcast({"event": "new_case", "case": payload})
            return verdict(case, assessment)
        except Exception as exc:
            async with SessionLocal() as db:
                record = await db.get(TransactionProcessing, record_id)
                if record.state != "COMPLETED":
                    record.state, record.error = "FAILED", type(exc).__name__
                    record.updated_at = datetime.utcnow()
                    await db.commit()
            raise


async def retry_pending():
    async with SessionLocal() as db:
        rows = (await db.execute(select(TransactionProcessing).where(
            TransactionProcessing.source_table == "api", TransactionProcessing.state != "COMPLETED",
            TransactionProcessing.attempts < 10,
            TransactionProcessing.updated_at < datetime.utcnow() - timedelta(seconds=30)
        ).limit(20))).scalars().all()
    for row in rows:
        try:
            await process(deserialize(row.payload))
        except Exception:
            log.exception("Processing retry failed for %s", row.id)
