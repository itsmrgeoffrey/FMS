import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.database import init_db
from backend.routers import cases, stats, ws, transactions, reports, audit, auth_routes, insights
from backend.routers import settings as settings_routes
from backend.services import poller

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    poll_task = asyncio.create_task(poller.poll_loop())
    yield
    poll_task.cancel()
    try:
        await poll_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="FMS — Fraud Monitoring System", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    # Instructs browsers to keep using HTTPS once served over it (no effect on plain HTTP).
    resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return resp

app.include_router(cases.router)
app.include_router(stats.router)
app.include_router(ws.router)
app.include_router(transactions.router)
app.include_router(reports.router)
app.include_router(settings_routes.router)
app.include_router(auth_routes.router)
app.include_router(audit.router)
app.include_router(insights.router)
