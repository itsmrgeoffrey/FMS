import asyncio
import logging
from datetime import datetime

from sqlalchemy import select

from backend.adapters.base import BaseAdapter
from backend.config import bank_config
from backend.database import SessionLocal
from backend.models import FraudCase, ProcessingState
from backend.services import processing

log = logging.getLogger(__name__)

_running = False
_last_poll_at: datetime | None = None
_last_error: str | None = None
_adapter: BaseAdapter | None = None
# Last observed bank-DB reachability, recorded by the poller so status endpoints
# can report it without opening their own connection. None = not yet checked.
_connect_ok: bool | None = None
_connect_checked_at: datetime | None = None


def get_adapter() -> BaseAdapter:
    global _adapter
    if _adapter is None:
        db_type = bank_config.get("database", {}).get("type", "mysql").lower()
        kwargs = dict(db_config=bank_config["database"], tables_config=bank_config.get("tables", {}))
        if db_type == "mssql":
            from backend.adapters.mssql import MSSQLAdapter as A
        elif db_type in ("postgres", "postgresql"):
            from backend.adapters.postgres import PostgresAdapter as A
        elif db_type == "oracle":
            from backend.adapters.oracle import OracleAdapter as A
        else:
            from backend.adapters.mysql import MySQLAdapter as A
        _adapter = A(**kwargs)
    return _adapter


async def _load_checkpoint(table_key: str) -> str | None:
    async with SessionLocal() as db:
        state = await db.get(ProcessingState, table_key)
        # An existing NULL cursor marks a source that was empty at initialization.
        return (state.last_processed_id or "") if state else None


async def _save_checkpoint(table_key: str, last_id: str | None) -> None:
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
        await _save_checkpoint(table_key, latest)
        log.info("[%s] Initial cursor: %s. Existing rows are baseline only; monitoring from next poll.",
                 table_key, latest if latest is not None else "empty source")
        return

    table_keys = list(bank_config.get("tables", {}).keys())
    new_txns = await adapter.fetch_new_transactions(table_key, since_id)

    if not new_txns:
        return

    log.info(f"[{table_key}] {len(new_txns)} new transaction(s) to analyze")

    for txn in new_txns:
        try:
            history = await adapter.fetch_account_history(txn.account_id, table_keys, history_days)
            history = [h for h in history if (h.source_table, h.id) != (txn.source_table, txn.id)]

            # analyze() is resilient to LLM failure — it always returns a result
            # built from the deterministic risk engine, so an AI outage can never
            # cause a transaction to be silently dropped.
            await processing.process(txn, history)
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
    global _last_error, _connect_ok, _connect_checked_at
    try:
        if await adapter.is_connected():
            _connect_ok, _connect_checked_at = True, datetime.utcnow()
            return True
        await adapter.connect()
        log.info("Bank DB connection (re)established")
        _connect_ok, _connect_checked_at = True, datetime.utcnow()
        return True
    except Exception as e:
        _last_error = f"bank DB connect failed: {e}"
        _connect_ok, _connect_checked_at = False, datetime.utcnow()
        log.error(_last_error)
        return False


def last_connect_ok() -> bool | None:
    """Whether the bank DB was reachable on the poller's last check.

    Passive: reports what the poller already observed rather than opening a new
    connection, so status endpoints never generate traffic to the institution's
    database. None means the poller has not checked yet (e.g. API-push mode, or
    before the first cycle completes).
    """
    return _connect_ok


def last_connect_checked_at() -> datetime | None:
    return _connect_checked_at


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

        # API-only mode: institutions push transactions to /ingest — no bank DB
        # is configured or touched. The poller idles.
        if monitoring.get("mode", "poll") == "api":
            _last_poll_at = datetime.utcnow()
            _last_error = None
            await asyncio.sleep(interval)
            continue
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
