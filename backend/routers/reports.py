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
from datetime import datetime, date, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import require_api_key
from backend.config import bank_config
from backend.database import get_db
from backend.models import FraudCase

# A SAR must generally be filed within 30 calendar days of initial detection
# (31 CFR 1020.320(b)(3)); FMS uses the case creation time as the detection date.
SAR_FILING_WINDOW_DAYS = 30

router = APIRouter(prefix="/reports", tags=["reports"], dependencies=[Depends(require_api_key)])

_CTR_COLUMNS = [
    "case_id", "created_at", "account_id", "direction", "currency", "amount",
    "counterparty_name", "counterparty_account", "channel", "ctr_reason", "status",
]
_SAR_COLUMNS = [
    "case_id", "created_at", "account_id", "direction", "currency", "amount",
    "counterparty_name", "counterparty_account", "channel", "fraud_type",
    "confidence", "risk_score", "sar_reason", "status",
    "detection_date", "filing_deadline", "days_remaining",
]


def _sar_deadline(case: FraudCase) -> dict:
    detected = case.created_at
    deadline = detected + timedelta(days=SAR_FILING_WINDOW_DAYS)
    return {
        "detection_date": detected.date().isoformat(),
        "filing_deadline": deadline.date().isoformat(),
        "days_remaining": (deadline.date() - datetime.utcnow().date()).days,
    }


def _institution() -> dict:
    inst = bank_config.get("institution", {}) or {}
    return {
        "name": inst.get("name", ""),
        "ein": inst.get("ein", ""),
        "address": inst.get("address", ""),
        "city": inst.get("city", ""),
        "state": inst.get("state", ""),
        "zip": inst.get("zip", ""),
        "primary_regulator": inst.get("primary_regulator", ""),
    }


# Map FMS fraud typologies to FinCEN SAR (Form 111) suspicious-activity
# categories. Structuring maps to Item 32 (Structuring); most others fall under
# Item 34 (Fraud) or Item 38 (Other) with a free-text description.
def _sar_activity_category(fraud_type: str | None) -> dict:
    ft = (fraud_type or "").lower()
    if "smurfing" in ft or "structuring" in ft or "near-threshold" in ft or "velocity" in ft:
        return {"item": "32", "category": "Structuring", "subtype": fraud_type or ""}
    if "takeover" in ft:
        return {"item": "35", "category": "Fraud", "subtype": "Account takeover"}
    if "invoice" in ft or "payment" in ft or "transfer" in ft:
        return {"item": "34", "category": "Fraud", "subtype": fraud_type or ""}
    if "sanction" in ft:
        return {"item": "38", "category": "Other", "subtype": "OFAC sanctions match"}
    return {"item": "38", "category": "Other", "subtype": fraud_type or "unusual activity"}


def _fincen_ctr_record(case: FraudCase) -> dict:
    """Form 112 (CTR) filing worksheet for one case. Items FMS cannot know
    (person identifiers, ID documents) are explicit nulls for manual completion."""
    return {
        "form": "FinCEN Form 112 (CTR)",
        "case_id": case.id,
        "part_i_person": {
            "item_4_individuals_last_name_or_entity": case.counterparty_name,
            "item_20_account_numbers": [case.account_id, case.counterparty_account],
            "item_2a_person_conducting_on_own_behalf": None,   # requires KYC data
            "identification_items_16_19": None,                 # requires ID documents
        },
        "part_ii_transaction": {
            "item_23_date_of_transaction": case.timestamp.date().isoformat() if case.timestamp else None,
            "item_25_cash_in" if case.direction == "INWARD" else "item_27_cash_out": {
                "amount": case.amount,
                "currency": case.currency,
            },
            "item_24_foreign_currency": case.currency != "USD",
            "trigger": case.ctr_reason,
        },
        "part_iii_institution": _institution(),
        "requires_manual_completion": [
            "Part I person identifiers (name components, address, TIN, DOB, ID)",
            "Item 24 foreign-currency details (if applicable)",
            "Filing contact information",
        ],
    }


def _fincen_sar_record(case: FraudCase) -> dict:
    """Form 111 (SAR) filing worksheet for one case, including the 30-day clock."""
    activity = _sar_activity_category(case.fraud_type)
    return {
        "form": "FinCEN Form 111 (SAR)",
        "case_id": case.id,
        "deadline": _sar_deadline(case),
        "part_i_subject": {
            "item_9_subject_name": case.counterparty_name,
            "item_24_account_numbers": [case.account_id, case.counterparty_account],
            "identifiers": None,                                # requires KYC data
        },
        "part_ii_suspicious_activity": {
            "item_29_amount_involved": {"amount": case.amount, "currency": case.currency},
            "item_30_date_range": {
                "from": case.timestamp.date().isoformat() if case.timestamp else None,
                "to": case.timestamp.date().isoformat() if case.timestamp else None,
            },
            "activity_category": activity,
            "instruments": {"channel": case.channel, "direction": case.direction},
        },
        "part_iv_filing_institution": _institution(),
        "narrative_draft": {
            "summary": case.ai_summary,
            "detection_reasons": case.reasons,
            "system_risk_score": case.risk_score,
        },
        "requires_manual_completion": [
            "Subject identifiers (address, TIN, DOB, ID) from KYC records",
            "Officer review and final narrative (the draft is system-generated)",
            "Continuing-activity determination if related SARs exist",
        ],
    }


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
    format: str = Query("json", pattern="^(json|csv|fincen)$"),
    db: AsyncSession = Depends(get_db),
):
    cases = await _fetch(db, FraudCase.ctr_required == True, date_from, date_to)  # noqa: E712
    if format == "fincen":
        return {
            "report": "CTR filing worksheets (FinCEN Form 112)",
            "count": len(cases),
            "note": "Pre-filled from transaction data; items listed under "
                    "requires_manual_completion need KYC records and officer review.",
            "items": [_fincen_ctr_record(c) for c in cases],
        }
    rows = [_row(c, _CTR_COLUMNS) for c in cases]
    if format == "csv":
        return _csv_response(rows, _CTR_COLUMNS, "ctr_report.csv")
    return {"report": "CTR", "count": len(rows), "items": rows}


@router.get("/sar")
async def sar_report(
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    format: str = Query("json", pattern="^(json|csv|fincen)$"),
    db: AsyncSession = Depends(get_db),
):
    cases = await _fetch(db, FraudCase.sar_recommended == True, date_from, date_to)  # noqa: E712
    if format == "fincen":
        return {
            "report": "SAR filing worksheets (FinCEN Form 111)",
            "count": len(cases),
            "filing_window_days": SAR_FILING_WINDOW_DAYS,
            "note": "Pre-filled from transaction data; the narrative draft and "
                    "subject identifiers require officer review before filing.",
            "items": [_fincen_sar_record(c) for c in cases],
        }
    rows = [{**_row(c, _SAR_COLUMNS), **_sar_deadline(c)} for c in cases]
    if format == "csv":
        return _csv_response(rows, _SAR_COLUMNS, "sar_report.csv")
    return {"report": "SAR", "count": len(rows), "items": rows}
