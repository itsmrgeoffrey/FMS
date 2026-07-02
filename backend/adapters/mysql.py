import logging
from datetime import datetime
import aiomysql
from backend.adapters.base import BaseAdapter, NormalizedTransaction

log = logging.getLogger(__name__)


class MySQLAdapter(BaseAdapter):
    def __init__(self, db_config: dict, tables_config: dict):
        self._db_cfg = db_config
        self._tables = tables_config  # {"inward": {...}, "outward": {...}}
        self._pool: aiomysql.Pool | None = None

    async def connect(self) -> None:
        self._pool = await aiomysql.create_pool(
            host=self._db_cfg["host"],
            port=int(self._db_cfg.get("port", 3306)),
            user=self._db_cfg["user"],
            password=self._db_cfg["password"],
            db=self._db_cfg["database"],
            autocommit=True,
            minsize=1,
            maxsize=5,
        )
        log.info("Connected to bank MySQL database")

    async def disconnect(self) -> None:
        if self._pool:
            self._pool.close()
            await self._pool.wait_closed()

    async def is_connected(self) -> bool:
        if not self._pool:
            return False
        try:
            async with self._pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT 1")
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
        )

    async def fetch_new_transactions(
        self, table_key: str, since_id: str | None, limit: int = 100
    ) -> list[NormalizedTransaction]:
        if table_key not in self._tables:
            return []

        table = self._table_name(table_key)
        id_col = self._col(table_key, "id")
        ts_col = self._col(table_key, "timestamp")

        if since_id:
            sql = f"SELECT * FROM `{table}` WHERE `{id_col}` > %s ORDER BY `{id_col}` ASC LIMIT %s"
            params = (since_id, limit)
        else:
            # First run: grab the most recent batch to establish a checkpoint
            sql = f"SELECT * FROM `{table}` ORDER BY `{ts_col}` DESC LIMIT %s"
            params = (limit,)

        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(sql, params)
                rows = await cur.fetchall()

        if not since_id:
            # On first run return nothing — just establish checkpoint so we catch future txns
            return []

        return [self._row_to_txn(dict(r), table_key) for r in rows]

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

            sql = (
                f"SELECT * FROM `{table}` WHERE `{acc_col}` = %s "
                f"AND `{ts_col}` >= DATE_SUB(NOW(), INTERVAL %s DAY) "
                f"ORDER BY `{ts_col}` DESC"
            )
            async with self._pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cur:
                    await cur.execute(sql, (account_id, history_days))
                    rows = await cur.fetchall()

            results.extend(self._row_to_txn(dict(r), table_key) for r in rows)

        results.sort(key=lambda t: t.timestamp, reverse=True)
        return results

    async def get_last_id(self, table_key: str) -> str | None:
        if table_key not in self._tables:
            return None
        table = self._table_name(table_key)
        id_col = self._col(table_key, "id")
        ts_col = self._col(table_key, "timestamp")
        sql = f"SELECT `{id_col}` FROM `{table}` ORDER BY `{ts_col}` DESC LIMIT 1"
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql)
                row = await cur.fetchone()
        return str(row[0]) if row else None
