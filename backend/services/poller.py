import asyncio
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.adapters.base import BaseAdapter
from backend.config import bank_config
from backend.database import SessionLocal
from backend.models import FraudCase, ProcessingState
from backend.services import analyzer
from backend.services.broadcaster import broadcaster
from backend.services import emailer

log = logging.getLogger(__name__)

_running = False
_last_poll_at: datetime | None = None
_last_error: str | None = None
_adapter: BaseAdapter | None = None


def get_adapter() -> BaseAdapter:
    global _adapter
    if _adapter is None:
        db_type = bank_config.get("database", {}).get("type", "mysql").lower()
        if db_type == "mssql":
            from backend.adapters.mssql import MSSQLAdapter
            _adapter = MSSQLAdapter(
                db_config=bank_config["database"],
                tables_config=bank_config.get("tables", {}),
            )
        else:
            from backend.adapters.mysql import MySQLAdapter
            _adapter = MySQLAdapter(
                db_config=bank_config["database"],
                tables_config=bank_config.get("tables", {}),
            )
    return _adapter


async def _load_checkpoint(table_key: str) -> str | None:
    async with SessionLocal() as db:
        state = await db.get(ProcessingState, table_key)
        return state.last_processed_id if state else None


async def _save_checkpoint(table_key: str, last_id: str) -> None:
    async with SessionLocal() as db:
        state = await db.get(ProcessingState, table_key)
        if state:
            state.last_processed_id = last_id
            state.last_processed_at = datetime.utcnow()
            state.updated_at = datetime.utcnow()
        else:
            state = ProcessingState(
                table_key=table_key,
                last_processed_id=last_id,
                last_processed_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(state)
        await db.commit()


async def _case_exists(source_table: str, source_txn_id: str) -> bool:
    async with SessionLocal() as db:
        result = await db.execute(
            select(FraudCase.id).where(
                FraudCase.source_table == source_table,
                FraudCase.source_txn_id == source_txn_id,
            )
        )
        return result.first() is not None


async def _process_table(adapter: BaseAdapter, table_key: str, history_days: int) -> None:
    since_id = await _load_checkpoint(table_key)

    # On first run: just set the checkpoint to the latest existing ID, start monitoring from now
    if since_id is None:
        latest = await adapter.get_last_id(table_key)
        if latest:
            await _save_checkpoint(table_key, latest)
            log.info(f"[{table_key}] First run — checkpoint set to {latest}. Monitoring from next poll.")
        return

    table_keys = list(bank_config.get("tables", {}).keys())
    new_txns = await adapter.fetch_new_transactions(table_key, since_id)

    if not new_txns:
        return

    log.info(f"[{table_key}] {len(new_txns)} new transaction(s) to analyze")

    for txn in new_txns:
        try:
            # Idempotency guard: a crash/replay must not re-flag a transaction that
            # already produced a case. If it exists, treat it as done and move the
            # checkpoint past it.
            if await _case_exists(txn.source_table, txn.id):
                log.info(f"[{table_key}] txn {txn.id} already has a case — skipping")
                await _save_checkpoint(table_key, txn.id)
                continue

            history = await adapter.fetch_account_history(txn.account_id, table_keys, history_days)
            history = [h for h in history if h.id != txn.id]  # exclude the txn itself

            # analyze() is resilient to LLM failure — it always returns a result
            # built from the deterministic risk engine, so an AI outage can never
            # cause a transaction to be silently dropped.
            result = await analyzer.analyze(txn, history)

            status = "OPEN" if result.is_fraudulent else "CLEAN"
            case = FraudCase(
                source_table=txn.source_table,
                source_txn_id=txn.id,
                account_id=txn.account_id,
                amount=txn.amount,
                direction=txn.direction,
                timestamp=txn.timestamp,
                counterparty_account=txn.counterparty_account,
                counterparty_name=txn.counterparty_name,
                channel=txn.channel,
                currency=txn.currency,
                reference=txn.reference,
                risk_score=result.risk_score,
                ctr_required=result.ctr_required,
                ctr_reason=result.ctr_reason,
                sar_recommended=result.sar_recommended,
                sar_reason=result.sar_reason,
                sanctions_hit=result.sanctions_hit,
                sanctions_detail=result.sanctions_detail,
                confidence=result.confidence,
                fraud_type=result.fraud_type,
                reasons=result.reasons,
                ai_summary=result.summary,
                status=status,
            )
            try:
                async with SessionLocal() as db:
                    db.add(case)
                    await db.commit()
                    await db.refresh(case)
            except IntegrityError:
                # Unique (source_table, source_txn_id) tripped — another pass beat
                # us to it. Not an error; the transaction is accounted for.
                log.info(f"[{table_key}] txn {txn.id} already recorded (race) — skipping")
                await _save_checkpoint(table_key, txn.id)
                continue

            if result.is_fraudulent:
                log.warning(
                    f"FRAUD FLAGGED — account {txn.account_id} | {txn.currency} {txn.amount:,.2f} "
                    f"| confidence={result.confidence} | type={result.fraud_type}"
                    f"{' | SAR recommended' if result.sar_recommended else ''}"
                    f"{' | *** OFAC SANCTIONS MATCH ***' if result.sanctions_hit else ''}"
                )
                case_dict = {
                    "id": case.id,
                    "account_id": case.account_id,
                    "amount": case.amount,
                    "currency": case.currency,
                    "direction": case.direction,
                    "confidence": case.confidence,
                    "fraud_type": case.fraud_type,
                    "counterparty_name": case.counterparty_name,
                    "counterparty_account": case.counterparty_account,
                    "channel": case.channel,
                    "reasons": case.reasons,
                    "ai_summary": case.ai_summary,
                    "ctr_required": case.ctr_required,
                    "sar_recommended": case.sar_recommended,
                    "sanctions_hit": case.sanctions_hit,
                    "sanctions_detail": case.sanctions_detail,
                    "created_at": str(case.created_at),
                }
                await broadcaster.broadcast({"event": "new_case", "case": case_dict})
                # Send email off the event loop without blocking the poller. Use the
                # running loop (get_event_loop() is deprecated inside a coroutine).
                loop = asyncio.get_running_loop()
                loop.run_in_executor(None, emailer.send_fraud_alert, case_dict)
            else:
                log.info(f"[{table_key}] txn {txn.id} — clean (risk={result.confidence})")

            # Advance the checkpoint only after the case is durably committed. If we
            # crash before this, the transaction is re-fetched next cycle and the
            # dedup guard above prevents a duplicate case.
            await _save_checkpoint(table_key, txn.id)

        except Exception as e:
            # A transient error (bank DB read, local DB write) — do NOT advance the
            # checkpoint. Stop this table for this cycle and retry the same
            # transaction next poll rather than skipping it. Never-miss beats
            # never-stall for a compliance tool.
            log.error(f"[{table_key}] Error processing txn {txn.id}: {e} — will retry next cycle")
            raise


async def _ensure_connected(adapter: BaseAdapter) -> bool:
    """Connect if not already connected. Returns True on success."""
    try:
        if await adapter.is_connected():
            return True
        await adapter.connect()
        log.info("Bank DB connection (re)established")
        return True
    except Exception as e:
        global _last_error
        _last_error = f"bank DB connect failed: {e}"
        log.error(_last_error)
        return False


async def poll_loop() -> None:
    global _running, _last_poll_at, _last_error

    adapter = get_adapter()
    table_keys = list(bank_config.get("tables", {}).keys())

    _running = True
    log.info(f"Poller started — watching tables: {table_keys}")

    while _running:
        # Re-read monitoring settings every cycle so changes made in the
        # Settings UI apply without a restart.
        monitoring = bank_config.get("monitoring", {})
        interval = int(monitoring.get("poll_interval_seconds", 30))
        history_days = int(monitoring.get("history_days", 90))
        try:
            # Reconnect transparently if the bank DB was never up or dropped.
            if not await _ensure_connected(adapter):
                await asyncio.sleep(interval)
                continue

            for table_key in table_keys:
                await _process_table(adapter, table_key, history_days)
            _last_poll_at = datetime.utcnow()
            _last_error = None
        except Exception as e:
            # Includes transient per-transaction errors re-raised from _process_table
            # (checkpoint not advanced, so the same work retries next cycle).
            _last_error = str(e)
            log.error(f"Poll cycle error: {e}")

        await asyncio.sleep(interval)

    try:
        await adapter.disconnect()
    except Exception:
        pass


def is_running() -> bool:
    return _running


def last_poll_at() -> datetime | None:
    return _last_poll_at


def last_error() -> str | None:
    return _last_error
