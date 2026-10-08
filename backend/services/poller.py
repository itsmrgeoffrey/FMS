import asyncio
import json
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
_adapters: dict[str, BaseAdapter] = {}
_shared_adapter: BaseAdapter | None = None
# Last observed bank-DB reachability, recorded by the poller so status endpoints
# can report it without opening their own connection. None = not yet checked.
_connect_ok: bool | None = None
_connect_checked_at: datetime | None = None
_source_connections: dict[str, dict] = {}


def _adapter_type(db_type: str):
    db_type = db_type.lower()
    if db_type == "mssql":
        from backend.adapters.mssql import MSSQLAdapter as adapter_type
    elif db_type in ("postgres", "postgresql"):
        from backend.adapters.postgres import PostgresAdapter as adapter_type
    elif db_type == "oracle":
        from backend.adapters.oracle import OracleAdapter as adapter_type
    else:
        from backend.adapters.mysql import MySQLAdapter as adapter_type
    return adapter_type


def source_database(table_key: str) -> dict:
    """Effective connection for a source; a nested override is optional."""
    table = (bank_config.get("tables", {}) or {}).get(table_key, {}) or {}
    return table.get("database") or bank_config.get("database", {}) or {"type": "mysql"}


def get_adapters() -> dict[str, BaseAdapter]:
    """Return source adapters, sharing one connection when database settings match."""
    global _adapters
    table_configs = bank_config.get("tables", {}) or {}
    if _adapters and set(_adapters) == set(table_configs):
        return _adapters

    grouped: dict[str, tuple[dict, dict]] = {}
    for table_key, table_config in table_configs.items():
        db_config = source_database(table_key)
        fingerprint = json.dumps(db_config, sort_keys=True, default=str)
        if fingerprint not in grouped:
            grouped[fingerprint] = (db_config, {})
        grouped[fingerprint][1][table_key] = table_config

    adapters: dict[str, BaseAdapter] = {}
    for db_config, tables_config in grouped.values():
        adapter = _adapter_type(db_config.get("type", "mysql"))(
            db_config=db_config, tables_config=tables_config,
        )
        for table_key in tables_config:
            adapters[table_key] = adapter
    _adapters = adapters
    return _adapters


def get_adapter(table_key: str | None = None) -> BaseAdapter:
    global _shared_adapter
    if table_key == "shared":
        if _shared_adapter is None:
            db_config = bank_config.get("database", {}) or {"type": "mysql"}
            _shared_adapter = _adapter_type(db_config.get("type", "mysql"))(
                db_config=db_config, tables_config=bank_config.get("tables", {}) or {},
            )
        return _shared_adapter
    adapters = get_adapters()
    if table_key is not None:
        if table_key not in adapters:
            raise KeyError(f"No '{table_key}' transaction source is configured")
        return adapters[table_key]
    if adapters:
        return next(iter(adapters.values()))

    # Retain a useful connection object for the shared-database test before
    # table mappings have been configured.
    db_config = bank_config.get("database", {}) or {"type": "mysql"}
    if _shared_adapter is None:
        _shared_adapter = _adapter_type(db_config.get("type", "mysql"))(
            db_config=db_config, tables_config={},
        )
    return _shared_adapter


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


async def _process_table(
    adapter: BaseAdapter,
    table_key: str,
    history_days: int,
    source_adapters: dict[str, BaseAdapter] | None = None,
) -> None:
    since_id = await _load_checkpoint(table_key)

    # On first run: just set the checkpoint to the latest existing ID, start monitoring from now
    if since_id is None:
        latest = await adapter.get_last_id(table_key)
        await _save_checkpoint(table_key, latest)
        log.info("[%s] Initial cursor: %s. Existing rows are baseline only; monitoring from next poll.",
                 table_key, latest if latest is not None else "empty source")
        return

    new_txns = await adapter.fetch_new_transactions(table_key, since_id)

    if not new_txns:
        return

    log.info(f"[{table_key}] {len(new_txns)} new transaction(s) to analyze")

    for txn in new_txns:
        try:
            configured = source_adapters or {
                key: adapter for key in (bank_config.get("tables", {}) or {table_key: {}})
            }
            history: list = []
            by_adapter: dict[int, tuple[BaseAdapter, list[str]]] = {}
            for source_key, source_adapter in configured.items():
                identity = id(source_adapter)
                if identity not in by_adapter:
                    by_adapter[identity] = (source_adapter, [])
                by_adapter[identity][1].append(source_key)
            for history_adapter, source_keys in by_adapter.values():
                history.extend(await history_adapter.fetch_account_history(
                    txn.account_id, source_keys, history_days,
                ))
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


async def _ensure_connected(adapter: BaseAdapter, source_keys: list[str] | None = None) -> bool:
    """Connect if not already connected. Returns True on success."""
    global _last_error, _connect_ok, _connect_checked_at
    try:
        if await adapter.is_connected():
            _connect_ok, _connect_checked_at = True, datetime.utcnow()
            for key in source_keys or []:
                _source_connections[key] = {"connected": True, "checked_at": _connect_checked_at, "error": None}
            return True
        await adapter.connect()
        log.info("Bank DB connection (re)established")
        _connect_ok, _connect_checked_at = True, datetime.utcnow()
        for key in source_keys or []:
            _source_connections[key] = {"connected": True, "checked_at": _connect_checked_at, "error": None}
        return True
    except Exception as e:
        _last_error = f"bank DB connect failed: {e}"
        _connect_ok, _connect_checked_at = False, datetime.utcnow()
        for key in source_keys or []:
            _source_connections[key] = {"connected": False, "checked_at": _connect_checked_at, "error": str(e)}
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


def connection_statuses() -> dict[str, dict]:
    return {
        key: {
            "connected": value.get("connected"),
            "checked_at": value["checked_at"].isoformat() + "Z" if value.get("checked_at") else None,
            "error": value.get("error"),
        }
        for key, value in _source_connections.items()
    }


async def poll_loop() -> None:
    global _running, _last_poll_at, _last_error, _connect_ok

    adapters = get_adapters()
    table_keys = list(adapters)

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
            # Connect every distinct source before analysis so history is never
            # evaluated from only part of the institution's configured feeds.
            connected = True
            seen: set[int] = set()
            for table_key, adapter in adapters.items():
                if id(adapter) in seen:
                    continue
                seen.add(id(adapter))
                keys = [key for key, candidate in adapters.items() if candidate is adapter]
                connected = await _ensure_connected(adapter, keys) and connected
            _connect_ok = connected
            if not connected:
                await asyncio.sleep(interval)
                continue

            for table_key, adapter in adapters.items():
                await _process_table(adapter, table_key, history_days, adapters)
            _last_poll_at = datetime.utcnow()
            _last_error = None
        except Exception as e:
            # Includes transient per-transaction errors re-raised from _process_table
            # (checkpoint not advanced, so the same work retries next cycle).
            _last_error = str(e)
            log.error(f"Poll cycle error: {e}")

        await asyncio.sleep(interval)

    try:
        seen: set[int] = set()
        for adapter in adapters.values():
            if id(adapter) not in seen:
                seen.add(id(adapter))
                await adapter.disconnect()
    except Exception:
        pass


def is_running() -> bool:
    return _running


def last_poll_at() -> datetime | None:
    return _last_poll_at


def last_error() -> str | None:
    return _last_error
