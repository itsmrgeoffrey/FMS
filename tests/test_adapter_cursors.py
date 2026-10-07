"""Adapter query contracts; these are not live database compatibility tests."""
import asyncio
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.parametrize("module,name", [
    ("mysql", "MySQLAdapter"), ("mssql", "MSSQLAdapter"),
    ("postgres", "PostgresAdapter"), ("oracle", "OracleAdapter"),
])
def test_adapter_initial_and_empty_source_cursor_queries(module, name):
    adapter_type = getattr(import_module(f"backend.adapters.{module}"), name)
    adapter = adapter_type({}, {"feed": {"table_name": "entries", "columns": {"id": "sequence_id", "timestamp": "posted_at"}}})
    calls = []

    class Cursor:
        description = [("sequence_id",)]
        async def execute(self, sql, params=()):
            calls.append((sql, params))
        async def fetchall(self):
            return [(8,)] if module == "oracle" else [{"sequence_id": 8}]
        async def fetchone(self):
            return (9,)
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass

    class Connection:
        def cursor(self, *args):
            return Cursor()
        async def fetch(self, sql, *params):
            calls.append((sql, params))
            return [{"sequence_id": 8}]
        async def fetchval(self, sql):
            calls.append((sql, ()))
            return 9
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass

    adapter._pool = SimpleNamespace(acquire=Connection)
    adapter._row_to_txn = lambda row, table: row
    if module == "mssql":
        adapter._submit = AsyncMock(side_effect=lambda fn: fn())
        def fetch_rows(sql, params):
            calls.append((sql, params))
            return [{"sequence_id": 8}]
        def execute(sql):
            calls.append((sql, ()))
            return SimpleNamespace(fetchone=lambda: (9,))
        adapter._fetch_rows = fetch_rows
        adapter._conn = SimpleNamespace(execute=execute)

    async def run():
        assert await adapter.fetch_new_transactions("feed", None) == []
        assert not calls
        assert await adapter.get_last_id("feed") == "9"
        assert "ORDER BY" in calls[-1][0] and "DESC" in calls[-1][0]
        assert "posted_at" not in calls[-1][0] and "sequence_id" in calls[-1][0]
        assert await adapter.fetch_new_transactions("feed", "", limit=2) == [{"sequence_id": 8}]
        assert "WHERE" not in calls[-1][0] and "ASC" in calls[-1][0]
        assert "posted_at" not in calls[-1][0]
        await adapter.fetch_new_transactions("feed", "0", limit=2)
        assert "WHERE" in calls[-1][0] and "0" in calls[-1][1]
        assert "ASC" in calls[-1][0]
    asyncio.run(run())
