import logging
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

log = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "fms.db"
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# Columns added after the first release. create_all() only creates missing
# tables — it never alters existing ones — so we add these by hand on startup
# for databases created before the column existed. Each entry is idempotent.
_ADDED_COLUMNS = {
    "fraud_cases": [
        ("sar_recommended", "BOOLEAN DEFAULT 0"),
        ("sar_reason", "TEXT"),
        ("sanctions_hit", "BOOLEAN DEFAULT 0"),
        ("sanctions_detail", "TEXT"),
    ],
}


async def _run_migrations(conn) -> None:
    for table, columns in _ADDED_COLUMNS.items():
        existing = {
            row[1]
            for row in (await conn.exec_driver_sql(f"PRAGMA table_info({table})")).all()
        }
        for name, ddl in columns:
            if name not in existing:
                await conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
                log.info(f"Migration: added {table}.{name}")

    # Enforce one-case-per-source-transaction on databases that predate the
    # unique constraint. Fails only if the table already contains duplicates —
    # in that case we log and leave the app running rather than crash on boot.
    try:
        await conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_case_source_txn "
            "ON fraud_cases (source_table, source_txn_id)"
        )
    except Exception as e:
        log.warning(
            f"Could not create uq_case_source_txn index (existing duplicates?): {e}"
        )


async def init_db():
    from backend import models  # noqa: F401 — ensures models are registered
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_migrations(conn)


async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
