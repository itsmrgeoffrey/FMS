import asyncio
import logging
import os
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.config import settings as app_settings, CORS_ORIGINS
from backend.database import init_db
from backend.logging_config import request_id_var, setup_logging
from backend.routers import approvals, cases, stats, ws, transactions, reports, audit, auth_routes, insights, ingest, risk
from backend.routers import settings as settings_routes, metrics as metrics_routes
from backend.services import poller, sanctions, metrics, delivery

# Configure logging before anything else emits records (env-controlled level and
# an optional rotating file — see backend/logging_config.py).
setup_logging()
log = logging.getLogger(__name__)


async def _ofac_refresh_loop():
    """Keep the OFAC screening lists current in production.

    On startup, if the downloaded SDN list is missing or older than the refresh
    interval, pull it immediately — so a fresh deploy stops screening against the
    tiny bundled sample within ~a minute instead of waiting a whole interval
    (which would otherwise leave a 24h hole in SDN coverage on every deploy).
    Then refresh on the configured schedule. Runs off the request path (executor)
    and fails safe: a download error keeps the current list rather than clearing
    it. Set FMS_OFAC_REFRESH_HOURS=0 to disable and manage the list yourself
    (mounted file / cron / scripts/update_ofac.py)."""
    hours = app_settings.ofac_refresh_hours
    if hours <= 0:
        return
    loop = asyncio.get_running_loop()

    async def _refresh(reason: str) -> None:
        try:
            count = await loop.run_in_executor(None, sanctions.refresh_from_treasury)
            log.info(f"OFAC list refreshed ({reason}): {count} entries")
        except Exception as e:
            # ERROR, not WARNING: this is the screening control. refresh_from_treasury
            # now refuses to overwrite a good list with an implausibly small one, so
            # a failure here means we are still screening against the PREVIOUS list —
            # correct behaviour, but it goes stale until someone acts on it.
            log.error(f"OFAC refresh failed ({reason}) — keeping current list: {e}")
        # Whatever happened, say plainly whether screening is actually working.
        st = sanctions.status()
        if not st["ok"]:
            log.error(f"SANCTIONS SCREENING NOT OPERATIONAL: {st['state']} — {st['detail']}")

    if sanctions.needs_refresh(hours):
        await _refresh("startup: list missing or stale")

    while True:
        await asyncio.sleep(hours * 3600)
        await _refresh("scheduled")


async def _retention_loop():
    """Optional retention enforcement (FMS_RETENTION_DAYS; 0 = off, the default).
    Purges RAW INGESTED TRANSACTION rows older than the configured age, once a
    day, and records each purge in the audit log. Cases, case actions, and the
    audit log itself are never auto-purged — they are the compliance record."""
    days = app_settings.retention_days
    if days <= 0:
        return
    if days < 1825:
        log.warning(
            "FMS_RETENTION_DAYS=%s is below the BSA five-year record-retention period "
            "(1825 days) — ensure another system retains these transaction records.", days,
        )
    from datetime import datetime, timedelta
    from sqlalchemy import delete
    from backend.database import SessionLocal
    from backend.models import IngestedTransaction
    from backend.routers import audit
    while True:
        try:
            cutoff = datetime.utcnow() - timedelta(days=days)
            async with SessionLocal() as db:
                result = await db.execute(
                    delete(IngestedTransaction).where(IngestedTransaction.timestamp < cutoff)
                )
                await db.commit()
            purged = result.rowcount or 0
            if purged:
                log.info("Retention purge: removed %s ingested-transaction rows older than %s days", purged, days)
                await audit.record("system", "RETENTION_PURGE",
                                   detail=f"purged {purged} ingested-transaction rows older than {days} days")
        except Exception as e:
            log.warning(f"Retention purge failed (will retry tomorrow): {e}")
        await asyncio.sleep(24 * 3600)


async def _metrics_flush_loop():
    """Persist buffered request counts every 30s so usage totals survive restarts."""
    while True:
        await asyncio.sleep(30)
        try:
            await metrics.flush()
        except Exception as e:
            log.warning(f"metrics flush failed (will retry): {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    poll_task = asyncio.create_task(poller.poll_loop())
    ofac_task = asyncio.create_task(_ofac_refresh_loop())
    retention_task = asyncio.create_task(_retention_loop())
    flush_task = asyncio.create_task(_metrics_flush_loop())
    recovery_task = asyncio.create_task(delivery.recovery_loop())
    yield
    try:
        await metrics.flush()  # persist any buffered counts on shutdown
    except Exception:
        pass
    for task in (poll_task, ofac_task, retention_task, flush_task, recovery_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="FMS — Fraud Monitoring System", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def ingest_request_tracing(request, call_next):
    """Give every /ingest call a short request id, log it end-to-end with
    latency, and return it as X-Request-ID so the sending institution can
    correlate. The id is attached (via a contextvar) to every log line emitted
    while handling the request, so one pushed transaction is traceable through
    the logs. Non-ingest paths are untouched."""
    if not request.url.path.startswith("/ingest"):
        return await call_next(request)
    rid = uuid.uuid4().hex[:12]
    token = request_id_var.set(rid)
    ilog = logging.getLogger("fms.ingest")
    client = request.client.host if request.client else "-"
    start = time.perf_counter()
    ilog.info("%s %s from %s", request.method, request.url.path, client)
    try:
        resp = await call_next(request)
        ilog.info("-> %s in %.1fms", resp.status_code, (time.perf_counter() - start) * 1000)
        resp.headers["X-Request-ID"] = rid
        return resp
    except Exception:
        ilog.exception("failed after %.1fms", (time.perf_counter() - start) * 1000)
        raise
    finally:
        request_id_var.reset(token)


@app.middleware("http")
async def security_headers(request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    # Instructs browsers to keep using HTTPS once served over it (no effect on plain HTTP).
    resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return resp


# ─── Abuse protection: request-body size limit + ingestion rate limiting ─────
_MAX_BODY_BYTES = int(os.getenv("FMS_MAX_BODY_BYTES", str(5 * 1024 * 1024)))  # 5 MB
_INGEST_HITS: dict[str, list[float]] = defaultdict(list)
_INGEST_MAX = int(os.getenv("FMS_INGEST_RATE_MAX", "120"))   # requests per IP per minute
_INGEST_WINDOW = 60.0


def _client_key(request) -> str:
    if app_settings.trust_x_forwarded_for:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.middleware("http")
async def limit_body_size(request, call_next):
    """Reject oversized request bodies — a cheap DoS guard. Chunked uploads with
    no Content-Length bypass this, but the app's inputs are small JSON anyway."""
    cl = request.headers.get("content-length")
    if cl:
        try:
            if int(cl) > _MAX_BODY_BYTES:
                return JSONResponse(status_code=413, content={"detail": "Request body too large"})
        except ValueError:
            pass
    return await call_next(request)


@app.middleware("http")
async def usage_metrics(request, call_next):
    """Count real API usage + latency for the public status page. Excludes
    health/metrics polling and CORS preflight so the numbers reflect actual
    usage, not infrastructure noise."""
    path = request.url.path
    if request.method == "OPTIONS" or path.startswith("/metrics") or path.startswith("/health"):
        return await call_next(request)
    start = time.perf_counter()
    resp = await call_next(request)
    try:
        metrics.record_request((time.perf_counter() - start) * 1000)
    except Exception:
        pass
    return resp


@app.middleware("http")
async def rate_limit_ingest(request, call_next):
    """Per-IP rate limit on the push-ingestion endpoints, on top of the API key —
    contains a compromised or runaway key. Login has its own throttle."""
    if request.url.path.startswith("/ingest"):
        key = _client_key(request)
        now = time.time()
        hits = [t for t in _INGEST_HITS[key] if now - t < _INGEST_WINDOW]
        if len(hits) >= _INGEST_MAX:
            _INGEST_HITS[key] = hits
            return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded — slow down."})
        hits.append(now)
        _INGEST_HITS[key] = hits
    return await call_next(request)

app.include_router(cases.router)
app.include_router(stats.router)
app.include_router(ws.router)
app.include_router(transactions.router)
app.include_router(reports.router)
app.include_router(settings_routes.router)
app.include_router(auth_routes.router)
app.include_router(audit.router)
app.include_router(insights.router)
app.include_router(ingest.router)
app.include_router(approvals.router)
app.include_router(risk.router)
app.include_router(metrics_routes.router)
