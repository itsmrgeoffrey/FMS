"""Read-only PostgreSQL adapter for the institution's transaction database."""
import logging
from datetime import datetime, timedelta

import asyncpg

from backend.adapters.base import BaseAdapter, NormalizedTransaction

log = logging.getLogger(__name__)


class PostgresAdapter(BaseAdapter):
    def __init__(self, db_config: dict, tables_config: dict):
        self._db_cfg = db_config
        self._tables = tables_config
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        cfg = self._db_cfg
        self._pool = await asyncpg.create_pool(
            host=cfg["host"], port=int(cfg.get("port", 5432)),
            user=cfg["user"], password=cfg["password"], database=cfg["database"],
            min_size=1, max_size=5,
            ssl="require" if cfg.get("encrypt") else None,
        )
        log.info("Connected to bank PostgreSQL database")

    async def disconnect(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def is_connected(self) -> bool:
        if not self._pool:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception:
            return False

    def _col(self, table_key: str, field: str) -> str | None:
        return self._tables.get(table_key, {}).get("columns", {}).get(field)

    def _row_to_txn(self, row, table_key: str) -> NormalizedTransaction:
        cols = self._tables[table_key]["columns"]

        def get(field: str):
            col = cols.get(field)
            return row[col] if col and col in row.keys() else None

        ts = get("timestamp")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        elif ts is None:
            ts = datetime.utcnow()

        return NormalizedTransaction(
            id=str(get("id") or ""), account_id=str(get("account_id") or ""),
            amount=float(get("amount") or 0),
            direction="INWARD" if table_key == "inward" else "OUTWARD",
            timestamp=ts,
            counterparty_account=str(get("counterparty_account") or "") or None,
            counterparty_name=str(get("counterparty_name") or "") or None,
            channel=str(get("channel") or "") or None,
            currency=str(get("currency") or "USD"),
            reference=str(get("reference") or "") or None,
            status=str(get("status") or "") or None,
            source_table=table_key,
            batch_id=str(get("batch_id") or "") or None,
        )

    async def fetch_new_transactions(self, table_key, since_id, limit=100):
        if table_key not in self._tables:
            return []
        table = self._tables[table_key]["table_name"]
        id_col = self._col(table_key, "id")
        if not since_id:
            return []
        sql = f'SELECT * FROM "{table}" WHERE "{id_col}" > $1 ORDER BY "{id_col}" ASC LIMIT $2'
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, since_id, limit)
        return [self._row_to_txn(r, table_key) for r in rows]

    async def fetch_account_history(self, account_id, table_keys, history_days=90):
        results = []
        cutoff = datetime.utcnow() - timedelta(days=history_days)
        for table_key in table_keys:
            if table_key not in self._tables:
                continue
            table = self._tables[table_key]["table_name"]
            acc, ts = self._col(table_key, "account_id"), self._col(table_key, "timestamp")
            sql = f'SELECT * FROM "{table}" WHERE "{acc}" = $1 AND "{ts}" >= $2 ORDER BY "{ts}" DESC'
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(sql, account_id, cutoff)
            results.extend(self._row_to_txn(r, table_key) for r in rows)
        results.sort(key=lambda t: t.timestamp, reverse=True)
        return results

    async def get_last_id(self, table_key):
        if table_key not in self._tables:
            return None
        table = self._tables[table_key]["table_name"]
        id_col, ts_col = self._col(table_key, "id"), self._col(table_key, "timestamp")
        sql = f'SELECT "{id_col}" FROM "{table}" ORDER BY "{ts_col}" DESC LIMIT 1'
        async with self._pool.acquire() as conn:
            val = await conn.fetchval(sql)
        return str(val) if val is not None else None
