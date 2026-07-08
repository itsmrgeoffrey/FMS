"""Read-only Oracle adapter for the institution's transaction database.

Uses python-oracledb in thin mode (no Oracle client install required).
Implemented to the same contract as the other adapters; flagged in docs as
not yet integration-tested against a live Oracle instance.
"""
import logging
from datetime import datetime, timedelta

import oracledb

from backend.adapters.base import BaseAdapter, NormalizedTransaction

log = logging.getLogger(__name__)


class OracleAdapter(BaseAdapter):
    def __init__(self, db_config: dict, tables_config: dict):
        self._db_cfg = db_config
        self._tables = tables_config
        self._pool: oracledb.AsyncConnectionPool | None = None

    async def connect(self) -> None:
        cfg = self._db_cfg
        dsn = f"{cfg['host']}:{int(cfg.get('port', 1521))}/{cfg['database']}"
        self._pool = oracledb.create_pool_async(
            user=cfg["user"], password=cfg["password"], dsn=dsn, min=1, max=5,
        )
        log.info("Connected to bank Oracle database")

    async def disconnect(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def is_connected(self) -> bool:
        if not self._pool:
            return False
        try:
            async with self._pool.acquire() as conn:
                cur = conn.cursor()
                await cur.execute("SELECT 1 FROM dual")
                await cur.fetchone()
            return True
        except Exception:
            return False

    def _col(self, table_key: str, field: str) -> str | None:
        return self._tables.get(table_key, {}).get("columns", {}).get(field)

    def _rows_to_dicts(self, cur, rows) -> list[dict]:
        cols = [d[0].lower() for d in cur.description]
        return [dict(zip(cols, r)) for r in rows]

    def _row_to_txn(self, row: dict, table_key: str) -> NormalizedTransaction:
        cols = self._tables[table_key]["columns"]

        def get(field: str):
            col = cols.get(field)
            return row.get(col.lower()) if col else None

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
        if table_key not in self._tables or not since_id:
            return []
        table = self._tables[table_key]["table_name"]
        id_col = self._col(table_key, "id")
        sql = (f'SELECT * FROM "{table}" WHERE "{id_col}" > :1 '
               f'ORDER BY "{id_col}" ASC FETCH FIRST :2 ROWS ONLY')
        async with self._pool.acquire() as conn:
            cur = conn.cursor()
            await cur.execute(sql, [since_id, limit])
            rows = self._rows_to_dicts(cur, await cur.fetchall())
        return [self._row_to_txn(r, table_key) for r in rows]

    async def fetch_account_history(self, account_id, table_keys, history_days=90):
        results = []
        cutoff = datetime.utcnow() - timedelta(days=history_days)
        for table_key in table_keys:
            if table_key not in self._tables:
                continue
            table = self._tables[table_key]["table_name"]
            acc, ts = self._col(table_key, "account_id"), self._col(table_key, "timestamp")
            sql = f'SELECT * FROM "{table}" WHERE "{acc}" = :1 AND "{ts}" >= :2 ORDER BY "{ts}" DESC'
            async with self._pool.acquire() as conn:
                cur = conn.cursor()
                await cur.execute(sql, [account_id, cutoff])
                rows = self._rows_to_dicts(cur, await cur.fetchall())
            results.extend(self._row_to_txn(r, table_key) for r in rows)
        results.sort(key=lambda t: t.timestamp, reverse=True)
        return results

    async def get_last_id(self, table_key):
        if table_key not in self._tables:
            return None
        table = self._tables[table_key]["table_name"]
        id_col, ts_col = self._col(table_key, "id"), self._col(table_key, "timestamp")
        sql = f'SELECT "{id_col}" FROM "{table}" ORDER BY "{ts_col}" DESC FETCH FIRST 1 ROWS ONLY'
        async with self._pool.acquire() as conn:
            cur = conn.cursor()
            await cur.execute(sql)
            row = await cur.fetchone()
        return str(row[0]) if row else None
