"""Live operational metrics for the public status page.

Privacy-preserving: we record aggregate COUNTS only — never a user, device, IP,
or session identifier. Request volume is buffered in memory and flushed to the
`usage_daily` table on a timer so totals survive restarts/redeploys; everything
else is counted from tables that already exist (transactions, cases, logins).
"""
import time
from collections import deque
from datetime import datetime, timedelta

from sqlalchemy import func, select

from backend.database import SessionLocal
from backend.models import AuditLog, FraudCase, IngestedTransaction, UsageDaily

# Process start — "uptime" is how long this instance has been serving (resets on
# each deploy, which is honest; a true % needs an external monitor).
_START_MONO = time.monotonic()
_START_DT = datetime.utcnow()

# In-memory, flushed to the DB on a timer.
_req_delta = 0                      # requests counted since the last flush
_latencies: deque[float] = deque(maxlen=1000)   # recent request latencies, ms

# Short cache so a polling/public status page can't hammer the DB.
_cache: dict = {"ts": 0.0, "data": None}

# Loopback addresses. The demo seed writes a couple of LOGIN rows from 127.0.0.1
# so the Security Events view isn't empty; we keep those in the audit log but
# never count them as real sessions. A genuine deployed sign-in always records a
# non-loopback client/proxy IP, so the session count only grows on real logins.
_LOOPBACK_IPS = ("127.0.0.1", "::1", "localhost", "0.0.0.0")


def record_request(latency_ms: float) -> None:
    global _req_delta
    _req_delta += 1
    _latencies.append(latency_ms)


def _today() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


async def flush() -> None:
    """Persist the buffered request delta into today's usage_daily row."""
    global _req_delta
    if _req_delta <= 0:
        return
    delta, _req_delta = _req_delta, 0
    day = _today()
    try:
        async with SessionLocal() as db:
            row = (await db.execute(select(UsageDaily).where(UsageDaily.day == day))).scalar_one_or_none()
            if row is None:
                db.add(UsageDaily(day=day, requests=delta))
            else:
                row.requests = (row.requests or 0) + delta
            await db.commit()
    except Exception:
        # Never lose the delta to a transient DB hiccup — put it back to retry next tick.
        _req_delta += delta
        raise


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = max(0, min(len(s) - 1, int(round(p / 100 * len(s))) - 1))
    return round(s[idx], 1)


async def snapshot() -> dict:
    now_ts = time.monotonic()
    if _cache["data"] is not None and now_ts - _cache["ts"] < 10:
        return _cache["data"]

    now = datetime.utcnow()
    cutoff_24h = now - timedelta(hours=24)

    async with SessionLocal() as db:
        req_persisted = (await db.execute(
            select(func.coalesce(func.sum(UsageDaily.requests), 0))
        )).scalar_one()

        txn_total = (await db.execute(select(func.count()).select_from(IngestedTransaction))).scalar_one()
        txn_24h = (await db.execute(
            select(func.count()).select_from(IngestedTransaction).where(IngestedTransaction.received_at >= cutoff_24h)
        )).scalar_one()

        alert_total = (await db.execute(select(func.count()).select_from(FraudCase))).scalar_one()
        alert_24h = (await db.execute(
            select(func.count()).select_from(FraudCase).where(FraudCase.created_at >= cutoff_24h)
        )).scalar_one()

        # Genuine sign-ins only: real logins from a non-loopback IP. Seeded demo
        # LOGIN rows (127.0.0.1) stay in the audit log but don't inflate this.
        sessions_total = (await db.execute(
            select(func.count()).select_from(AuditLog).where(
                AuditLog.action == "LOGIN",
                AuditLog.ip.isnot(None),
                AuditLog.ip.notin_(_LOOPBACK_IPS),
            )
        )).scalar_one()

        # 7-day trend (per-day range filters keep this portable across SQLite/SQL Server).
        req_rows = dict((await db.execute(
            select(UsageDaily.day, UsageDaily.requests).where(UsageDaily.day >= (now - timedelta(days=6)).strftime("%Y-%m-%d"))
        )).all())

        trend = []
        for i in range(6, -1, -1):
            d0 = datetime(now.year, now.month, now.day) - timedelta(days=i)
            d1 = d0 + timedelta(days=1)
            key = d0.strftime("%Y-%m-%d")
            txn_day = (await db.execute(
                select(func.count()).select_from(IngestedTransaction)
                .where(IngestedTransaction.received_at >= d0, IngestedTransaction.received_at < d1)
            )).scalar_one()
            trend.append({"day": d0.strftime("%m/%d"), "requests": int(req_rows.get(key, 0)), "transactions": int(txn_day)})

    lat = list(_latencies)
    data = {
        "status": "operational",
        "uptime_seconds": int(time.monotonic() - _START_MONO),
        "serving_since": _START_DT.replace(microsecond=0).isoformat() + "Z",
        "requests_total": int(req_persisted) + _req_delta,
        "transactions_total": int(txn_total),
        "transactions_24h": int(txn_24h),
        "alerts_total": int(alert_total),
        "alerts_24h": int(alert_24h),
        "sessions_total": int(sessions_total),
        "latency_avg_ms": round(sum(lat) / len(lat), 1) if lat else 0.0,
        "latency_p95_ms": _percentile(lat, 95),
        "trend": trend,
    }
    _cache["ts"] = now_ts
    _cache["data"] = data
    return data
