import logging
import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

log = logging.getLogger(__name__)

# Load the selected environment file before reading the DB URL, independent of
# import order (FMS_ENV_FILE lets prod/test environments stay isolated).
load_dotenv(os.getenv("FMS_ENV_FILE", "").strip() or str(Path(__file__).parent.parent / ".env"))

# The FMS application store. Defaults to SQLite (portable, used by tests); set
# FMS_APP_DB_URL to a server database URL (e.g. SQL Server via mssql+aioodbc,
# or Postgres via postgresql+asyncpg) for a multi-user deployment.
# FMS_DB_PATH still lets a SQLite deployment keep the file on a volume.
DB_PATH = Path(os.getenv("FMS_DB_PATH", "") or Path(__file__).parent.parent / "fms.db")
DATABASE_URL = os.getenv("FMS_APP_DB_URL", "").strip() or f"sqlite+aiosqlite:///{DB_PATH}"

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
    "users": [
        ("email", "TEXT"),
    ],
}


async def _run_migrations(conn) -> None:
    # These are SQLite-specific retrofits (PRAGMA/ADD COLUMN) for evolving an
    # existing SQLite file. On a server database, create_all() builds every
    # table with all current columns, so nothing to retrofit.
    if conn.dialect.name != "sqlite":
        return
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

    # Unique index on user email (multiple NULLs allowed in SQLite for pre-existing
    # accounts that don't have an email yet).
    try:
        await conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email ON users (email)"
        )
    except Exception as e:
        log.warning(f"Could not create uq_users_email index (existing duplicate emails?): {e}")


async def init_db():
    from backend import models  # noqa: F401 — ensures models are registered
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_migrations(conn)


async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
