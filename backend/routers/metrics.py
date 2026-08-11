"""Public live-metrics endpoint powering the status page.

No auth: it exposes only aggregate operational counts (no user/device/IP data),
so it's safe to serve publicly — a live, independently-viewable status page.
"""
from fastapi import APIRouter

from backend.services import metrics

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/usage")
async def usage():
    return await metrics.snapshot()
