import asyncio
import logging
import threading
import pyodbc
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from backend.adapters.base import BaseAdapter, NormalizedTransaction

log = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=4)


class MSSQLAdapter(BaseAdapter):
    def __init__(self, db_config: dict, tables_config: dict):
        self._db_cfg = db_config
        self._tables = tables_config
        self._conn: pyodbc.Connection | None = None
        # A pyodbc connection is not safe for concurrent commands. The poller and
        # the /transactions inject endpoint both use this one connection, so every
        # operation on it is serialized through this lock.
        self._lock = threading.Lock()

    async def _submit(self, fn):
        """Run a blocking DB callable in the thread pool, serialized on _lock so
        only one command touches the shared connection at a time. Called from a
        coroutine, so get_running_loop() is the correct way to reach the loop."""
        lock = self._lock

        def guarded():
            with lock:
                return fn()

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_executor, guarded)

    def _make_conn_str(self) -> str:
        cfg = self._db_cfg
        host = cfg["host"]
        # Use named pipe for local "." connections, TCP for remote
        server = host if host == "." else f"{host},{cfg.get('port', 1433)}"
        encrypt = "yes" if cfg.get("encrypt") else "no"
        trust = "yes" if cfg.get("trust_server_certificate", True) else "no"
        base = (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={server};"
            f"DATABASE={cfg['database']};"
            f"Encrypt={encrypt};"
            f"TrustServerCertificate={trust};"
        )
        if cfg.get("trusted_connection"):
            return base + "Trusted_Connection=yes;"
        return base + f"UID={cfg['user']};PWD={cfg['password']};"

    async def connect(self) -> None:
        conn_str = self._make_conn_str()
        self._conn = await self._submit(lambda: pyodbc.connect(conn_str, autocommit=True))
        log.info("Connected to bank MSSQL database")

    async def disconnect(self) -> None:
        if self._conn:
            await self._submit(self._conn.close)
            self._conn = None

    async def is_connected(self) -> bool:
        if not self._conn:
            return False
        try:
            await self._submit(lambda: self._conn.execute("SELECT 1").fetchall())
            return True
        except Exception:
            return False

    def _col(self, table_key: str, field: str) -> str | None:
        return self._tables.get(table_key, {}).get("columns", {}).get(field)

    def _table_name(self, table_key: str) -> str:
        return self._tables[table_key]["table_name"]

    def _row_to_txn(self, row: dict, table_key: str) -> NormalizedTransaction:
        cols = self._tables[table_key]["columns"]
        direction = "INWARD" if table_key == "inward" else "OUTWARD"

        def get(field: str):
            col = cols.get(field)
            return row.get(col) if col else None

        ts = get("timestamp")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        elif ts is None:
            ts = datetime.utcnow()

        return NormalizedTransaction(
            id=str(get("id") or ""),
            account_id=str(get("account_id") or ""),
            amount=float(get("amount") or 0),
            direction=direction,
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

    def _fetch_rows(self, sql: str, params: tuple) -> list[dict]:
        cursor = self._conn.execute(sql, params)
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    async def fetch_new_transactions(
        self, table_key: str, since_id: str | None, limit: int = 100
    ) -> list[NormalizedTransaction]:
        if table_key not in self._tables:
            return []

        table = self._table_name(table_key)
        id_col = self._col(table_key, "id")
        ts_col = self._col(table_key, "timestamp")

        if since_id:
            sql = f"SELECT TOP {limit} * FROM [{table}] WHERE [{id_col}] > ? ORDER BY [{id_col}] ASC"
            rows = await self._submit(lambda: self._fetch_rows(sql, (since_id,)))
        else:
            sql = f"SELECT TOP {limit} * FROM [{table}] ORDER BY [{ts_col}] DESC"
            await self._submit(lambda: self._fetch_rows(sql, ()))
            return []  # First run — just establish checkpoint

        return [self._row_to_txn(r, table_key) for r in rows]

    async def fetch_account_history(
        self, account_id: str, table_keys: list[str], history_days: int = 90
    ) -> list[NormalizedTransaction]:
        results: list[NormalizedTransaction] = []

        for table_key in table_keys:
            if table_key not in self._tables:
                continue
            table = self._table_name(table_key)
            acc_col = self._col(table_key, "account_id")
            ts_col = self._col(table_key, "timestamp")

            # Date-range query captures full behavioural window regardless of transaction volume.
            # Bind -history_days so MSSQL computes the cutoff date server-side.
            sql = (
                f"SELECT * FROM [{table}] "
                f"WHERE [{acc_col}] = ? AND [{ts_col}] >= DATEADD(day, ?, GETDATE()) "
                f"ORDER BY [{ts_col}] DESC"
            )
            _sql, _acc, _days = sql, account_id, -history_days
            rows = await self._submit(lambda: self._fetch_rows(_sql, (_acc, _days)))
            results.extend(self._row_to_txn(r, table_key) for r in rows)

        results.sort(key=lambda t: t.timestamp, reverse=True)
        return results

    async def get_last_id(self, table_key: str) -> str | None:
        if table_key not in self._tables:
            return None
        table = self._table_name(table_key)
        id_col = self._col(table_key, "id")
        ts_col = self._col(table_key, "timestamp")
        sql = f"SELECT TOP 1 [{id_col}] FROM [{table}] ORDER BY [{ts_col}] DESC"

        def fetch():
            cursor = self._conn.execute(sql)
            row = cursor.fetchone()
            return str(row[0]) if row else None

        return await self._submit(fetch)

    async def execute_write(self, sql: str, params: tuple) -> None:
        """Run an INSERT/UPDATE on the shared connection, serialized on the lock
        so it can't collide with a poller read mid-flight."""
        await self._submit(lambda: self._conn.execute(sql, params))
