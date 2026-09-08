import logging
import os
from pathlib import Path
from urllib.parse import quote_plus, unquote_plus
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


def _ensure_mars(url: str) -> str:
    """SQL Server rejects overlapping result sets on a pooled connection unless
    Multiple Active Result Sets is enabled — surfacing as intermittent
    '[ODBC Driver 17 for SQL Server]Connection is busy with results for another
    command' 500s on endpoints that issue several queries (e.g. the dashboard).
    Enable MARS automatically for mssql+aioodbc URLs so every SQL Server
    deployment is correct without hand-editing the connection string. Idempotent;
    only touches the standard `?odbc_connect=` form and leaves other URLs alone."""
    if not url.lower().startswith("mssql") or "odbc_connect=" not in url:
        return url
    prefix, encoded = url.split("odbc_connect=", 1)
    if "&" in encoded:  # odbc_connect not the sole/last param — don't risk mangling
        return url
    conn_str = unquote_plus(encoded)
    if "mars_connection" in conn_str.lower():
        return url
    conn_str = conn_str.rstrip(";") + ";MARS_Connection=Yes;"
    log.info("Enabled MARS for SQL Server connection (prevents 'connection is busy' errors)")
    return prefix + "odbc_connect=" + quote_plus(conn_str)


DATABASE_URL = _ensure_mars(DATABASE_URL)

# pool_pre_ping avoids the other common server-DB failure mode: a pooled
# connection dropped by the server (idle timeout / restart) being handed to a
# request. Harmless for SQLite.
engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
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
        ("must_change_password", "BOOLEAN DEFAULT 0"),
    ],
}


# SQLite spellings above, translated for SQL Server. create_all() only fills in
# columns when it creates the table, so a server database that predates a column
# needs the same retrofit an existing SQLite file does.
_MSSQL_TYPES = {"BOOLEAN": "BIT", "TEXT": "NVARCHAR(MAX)"}


def _mssql_ddl(ddl: str) -> str:
    """Translate a SQLite column definition to its T-SQL equivalent."""
    parts = ddl.split(" ", 1)
    base = _MSSQL_TYPES.get(parts[0].upper(), parts[0])
    return base + (" " + parts[1] if len(parts) > 1 else "")


async def _add_missing_columns(conn) -> None:
    """Add columns introduced after a database was first created.

    Portable across SQLite and SQL Server: the column list comes from the
    SQLAlchemy inspector rather than a PRAGMA, and the ALTER is spelled per
    dialect (SQLite wants ADD COLUMN, T-SQL wants ADD). Idempotent — a column
    that already exists is skipped.
    """
    from sqlalchemy import inspect as sa_inspect

    dialect = conn.dialect.name
    if dialect not in ("sqlite", "mssql"):
        return  # unknown dialect: leave the schema alone rather than guess

    def _columns(sync_conn, table: str) -> set[str]:
        insp = sa_inspect(sync_conn)
        if table not in insp.get_table_names():
            return set()
        return {c["name"] for c in insp.get_columns(table)}

    for table, columns in _ADDED_COLUMNS.items():
        existing = await conn.run_sync(_columns, table)
        if not existing:
            continue  # table not created yet; create_all builds it complete
        for name, ddl in columns:
            if name in existing:
                continue
            if dialect == "sqlite":
                stmt = f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"
            else:
                stmt = f"ALTER TABLE {table} ADD {name} {_mssql_ddl(ddl)}"
            try:
                await conn.exec_driver_sql(stmt)
                log.info(f"Migration: added {table}.{name}")
            except Exception as e:
                log.warning(f"Could not add {table}.{name}: {e}")


async def _run_migrations(conn) -> None:
    # Column retrofits run on every supported dialect.
    await _add_missing_columns(conn)

    # The index retrofits below use SQLite-only syntax ("IF NOT EXISTS"), and a
    # server database gets these constraints from create_all(), so stop here.
    if conn.dialect.name != "sqlite":
        return

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
