"""Regulatory filing helpers.

Turns flagged cases into the two lists an SME's compliance officer actually needs
to hand to their filer:

  * CTR — every transaction at/above the cash-reporting threshold (FinCEN/BSA
    USD 10,000 or the local-currency equivalent).
  * SAR — every case where the system recommends a Suspicious Activity Report
    (structuring/smurfing, or suspicious activity above the SAR threshold).

Both are available as JSON (for the UI) or CSV (?format=csv, ready to open in a
spreadsheet or attach to a filing package).
"""
import csv
import io
from datetime import datetime, date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import require_api_key
from backend.database import get_db
from backend.models import FraudCase

router = APIRouter(prefix="/reports", tags=["reports"], dependencies=[Depends(require_api_key)])

_CTR_COLUMNS = [
    "case_id", "created_at", "account_id", "direction", "currency", "amount",
    "counterparty_name", "counterparty_account", "channel", "ctr_reason", "status",
]
_SAR_COLUMNS = [
    "case_id", "created_at", "account_id", "direction", "currency", "amount",
    "counterparty_name", "counterparty_account", "channel", "fraud_type",
    "confidence", "risk_score", "sar_reason", "status",
]


def _date_filters(date_from: date | None, date_to: date | None) -> list:
    filters = []
    if date_from:
        filters.append(FraudCase.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        filters.append(FraudCase.created_at <= datetime.combine(date_to, datetime.max.time()))
    return filters


def _row(case: FraudCase, columns: list[str]) -> dict:
    return {
        col: (case.id if col == "case_id" else getattr(case, col, None))
        for col in columns
    }


def _csv_response(rows: list[dict], columns: list[str], filename: str) -> StreamingResponse:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns)
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _fetch(db: AsyncSession, condition, date_from, date_to) -> list[FraudCase]:
    filters = [condition] + _date_filters(date_from, date_to)
    q = select(FraudCase).where(and_(*filters)).order_by(FraudCase.created_at.desc())
    result = await db.execute(q)
    return list(result.scalars().all())


@router.get("/ctr")
async def ctr_report(
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    format: str = Query("json", pattern="^(json|csv)$"),
    db: AsyncSession = Depends(get_db),
):
    cases = await _fetch(db, FraudCase.ctr_required == True, date_from, date_to)  # noqa: E712
    rows = [_row(c, _CTR_COLUMNS) for c in cases]
    if format == "csv":
        return _csv_response(rows, _CTR_COLUMNS, "ctr_report.csv")
    return {"report": "CTR", "count": len(rows), "items": rows}


@router.get("/sar")
async def sar_report(
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    format: str = Query("json", pattern="^(json|csv)$"),
    db: AsyncSession = Depends(get_db),
):
    cases = await _fetch(db, FraudCase.sar_recommended == True, date_from, date_to)  # noqa: E712
    rows = [_row(c, _SAR_COLUMNS) for c in cases]
    if format == "csv":
        return _csv_response(rows, _SAR_COLUMNS, "sar_report.csv")
    return {"report": "SAR", "count": len(rows), "items": rows}
