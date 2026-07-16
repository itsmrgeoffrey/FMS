"""Read-only aggregate endpoints powering the Customers, Rule Engine and Analytics pages."""
from datetime import datetime, date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, and_, case
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import require_admin, require_user
from backend.database import get_db
from backend.models import FraudCase, IngestedTransaction, RuleChange, User
from backend.services import analyzer as A
from backend.services import sanctions as S

router = APIRouter(tags=["insights"])

OPEN_STATUSES = ("OPEN", "UNDER_REVIEW")

# FinCEN National AML/CFT Priorities (June 30, 2021 — the operative set, which
# the 2026 AML/CFT Program rule proposal would require institutions to incorporate
# into their risk assessments) mapped honestly to FMS coverage. "direct" =
# detection signals target it; "partial" = FMS surfaces the money-movement
# mechanics but predicate-crime attribution is human work; "screening" =
# addressed via OFAC/PEP list screening rather than behavioral detection.
NATIONAL_PRIORITIES: list[dict] = [
    {"priority": "Corruption", "coverage": "screening",
     "how": "OFAC screening (e.g. Global Magnitsky programs) on every party; optional PEP list "
            "flags politically exposed persons for enhanced due diligence."},
    {"priority": "Cybercrime, including relevant cybersecurity and virtual-currency considerations",
     "coverage": "partial",
     "how": "Account-takeover typology (established account + new channel/odd hours/new counterparty). "
            "No virtual-asset-native analytics."},
    {"priority": "Foreign and domestic terrorist financing", "coverage": "screening",
     "how": "OFAC SDN screening (counter-terrorism programs) on every party; behavioral signals may "
            "surface funneling patterns, but TF identification requires human investigation."},
    {"priority": "Fraud", "coverage": "direct",
     "how": "Behavioral-deviation, invoice-fraud, account-takeover, new-counterparty, velocity and "
            "odd-hours signals target fraud typologies directly."},
    {"priority": "Transnational criminal organization activity", "coverage": "partial",
     "how": "Structuring/smurfing/velocity signals detect the laundering mechanics TCO proceeds use; "
            "attributing activity to a TCO is the investigator's determination."},
    {"priority": "Drug trafficking organization activity", "coverage": "partial",
     "how": "Structuring and multi-source smurfing detection — the classic placement patterns for "
            "drug proceeds — plus OFAC narcotics-program screening."},
    {"priority": "Human trafficking and human smuggling", "coverage": "partial",
     "how": "Funnel-style multi-source inflow detection; dedicated FinCEN HT advisory indicators "
            "(e.g. specific merchant patterns) are not modeled."},
    {"priority": "Proliferation financing", "coverage": "screening",
     "how": "OFAC SDN and Consolidated-list screening (non-proliferation programs) on every party."},
]


@router.get("/customers")
async def customers(
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_user),
):
    """Per-account rollup across all analyzed transactions."""
    rows = (await db.execute(
        select(
            FraudCase.account_id,
            func.count().label("txns"),
            func.sum(case((FraudCase.status != "CLEAN", 1), else_=0)).label("flagged"),
            func.sum(case((FraudCase.status.in_(OPEN_STATUSES), 1), else_=0)).label("open"),
            func.sum(case((FraudCase.sanctions_hit == True, 1), else_=0)).label("sanctions"),  # noqa: E712
            func.sum(case((FraudCase.sar_recommended == True, 1), else_=0)).label("sar"),        # noqa: E712
            func.max(FraudCase.risk_score).label("max_risk"),
            func.sum(FraudCase.amount).label("total_amount"),
            func.max(FraudCase.currency).label("currency"),
            func.max(FraudCase.created_at).label("last_activity"),
        )
        .group_by(FraudCase.account_id)
        .order_by(func.max(FraudCase.risk_score).desc())
        .limit(limit)
    )).all()

    return {
        "count": len(rows),
        "items": [
            {
                "account_id": r.account_id,
                "transactions": int(r.txns or 0),
                "flagged": int(r.flagged or 0),
                "open": int(r.open or 0),
                "sanctions_hits": int(r.sanctions or 0),
                "sar_count": int(r.sar or 0),
                "max_risk": r.max_risk,
                "total_amount": round(float(r.total_amount or 0), 2),
                "currency": r.currency,
                "last_activity": str(r.last_activity) if r.last_activity else None,
            }
            for r in rows
        ],
    }


@router.get("/analytics")
async def analytics(db: AsyncSession = Depends(get_db), _user: User = Depends(require_user)):
    """KPIs for the Analytics page — all computed from real case data."""
    today_start = datetime.combine(date.today(), datetime.min.time())

    async def count(*filters):
        stmt = select(func.count()).select_from(FraudCase)
        if filters:
            stmt = stmt.where(and_(*filters))
        return (await db.execute(stmt)).scalar_one()

    total = await count()
    flagged = await count(FraudCase.status != "CLEAN")
    open_cases = await count(FraudCase.status.in_(OPEN_STATUSES))
    alerts_today = await count(FraudCase.created_at >= today_start, FraudCase.status != "CLEAN")
    confirmed = await count(FraudCase.status == "CONFIRMED_FRAUD")
    dismissed = await count(FraudCase.status == "DISMISSED")
    resolved = confirmed + dismissed

    # Value flagged for review, per currency (mixed-currency safe).
    q = await db.execute(
        select(FraudCase.currency, func.sum(FraudCase.amount))
        .where(FraudCase.status != "CLEAN")
        .group_by(FraudCase.currency)
        .order_by(func.sum(FraudCase.amount).desc())
    )
    value_flagged = [{"currency": cur, "amount": round(float(total_amt or 0), 2)} for cur, total_amt in q.all()]

    # Top fraud types (flagged cases only).
    q = await db.execute(
        select(FraudCase.fraud_type, func.count())
        .where(FraudCase.fraud_type.isnot(None))
        .group_by(FraudCase.fraud_type)
        .order_by(func.count().desc())
    )
    top_fraud_types = [{"type": t, "count": c} for t, c in q.all()]

    return {
        "transactions_processed": total,
        "alerts_today": alerts_today,
        "open_cases": open_cases,
        "value_flagged": value_flagged,          # "Fraud Loss Prevented" — value surfaced for review
        "resolved": {"confirmed": confirmed, "dismissed": dismissed, "total": resolved},
        # False positive rate among REVIEWED (resolved) alerts; null until any are resolved.
        "false_positive_rate": (dismissed / resolved) if resolved else None,
        "top_fraud_types": top_fraud_types,
        "flagged_total": flagged,
    }


from pydantic import BaseModel


class ScreenRequest(BaseModel):
    names: list[str]


@router.post("/screening/check")
async def screening_check(body: ScreenRequest, _user: User = Depends(require_user)):
    """Batch-screen arbitrary names (e.g. your customer base) against the OFAC
    SDN list (+ configured PEP list). Returns only the hits."""
    if len(body.names) > 5000:
        return {"error": "Maximum 5,000 names per request"}
    hits = []
    for name in body.names:
        m = S.screen(name)
        if m:
            hits.append({
                "query": name, "matched_name": m.matched_name, "score": m.score,
                "list_type": m.list_type, "program": m.program, "source": m.source,
            })
    return {"screened": len(body.names), "hits": hits}


# ─── FinCEN 314(a) batch scan ─────────────────────────────────────────────────

class Scan314aRequest(BaseModel):
    csv_text: str | None = None    # the FinCEN 314(a) subject file, pasted/uploaded as CSV text
    names: list[str] | None = None # or a plain list of subject names
    threshold: float = 0.90


def _parse_314a_subjects(csv_text: str) -> list[str]:
    """Extract subject names from a 314(a) CSV. Handles the common layouts:
    a 'Business Name' or single 'Name' column, or 'Last Name' + 'First Name'
    (+ 'Middle Name') columns. Falls back to the first cell per row when no
    recognizable header is present."""
    import csv as _csv
    import io as _io

    rows = [r for r in _csv.reader(_io.StringIO(csv_text)) if any(c.strip() for c in r)]
    if not rows:
        return []

    header = [c.strip().lower() for c in rows[0]]

    def col(*want: str) -> int | None:
        for i, h in enumerate(header):
            if any(w in h for w in want):
                return i
        return None

    i_business = col("business name", "entity name")
    i_name = col("subject name") if col("subject name") is not None else (
        header.index("name") if "name" in header else None)
    i_last, i_first, i_middle = col("last name"), col("first name"), col("middle name")
    has_header = any(x is not None for x in (i_business, i_name, i_last))

    subjects: list[str] = []
    for r in (rows[1:] if has_header else rows):
        def cell(i: int | None) -> str:
            return r[i].strip() if i is not None and i < len(r) else ""
        name = ""
        if has_header:
            name = cell(i_business) or cell(i_name)
            if not name and cell(i_last):
                name = " ".join(p for p in (cell(i_first), cell(i_middle), cell(i_last)) if p)
        else:
            name = (r[0] or "").strip()
        if name:
            subjects.append(name)
    return subjects


@router.post("/screening/314a")
async def scan_314a(
    body: Scan314aRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Scan a FinCEN 314(a) subject list against every party FMS has seen
    (account holders and counterparties from ingested transactions, and case
    counterparties). Admin-only — 314(a) lists are confidential. Results are a
    screening aid: positive matches must be verified against your customer
    records and reported through FinCEN's Secure Information Sharing System by
    the institution; FMS does not transmit anything. The audit log records that
    a scan ran and the counts — never the subject names."""
    subjects = list(body.names or [])
    if body.csv_text:
        subjects += _parse_314a_subjects(body.csv_text)
    subjects = [s for s in {s.strip() for s in subjects} if s]
    if not subjects:
        return {"error": "No subject names found in the input."}
    if len(subjects) > 5000:
        return {"error": "Maximum 5,000 subjects per scan."}

    # Every party name FMS has seen, with where it appeared.
    parties: dict[str, dict] = {}   # normalized -> {name, roles, accounts, occurrences}

    def add_party(name: str | None, role: str, account: str | None):
        norm = S._normalize(name)
        if not norm:
            return
        p = parties.setdefault(norm, {"name": name, "roles": set(), "accounts": set(), "occurrences": 0})
        p["roles"].add(role)
        p["occurrences"] += 1
        if account:
            p["accounts"].add(account)

    for holder, cp, acct in (await db.execute(
        select(IngestedTransaction.account_holder_name,
               IngestedTransaction.counterparty_name,
               IngestedTransaction.account_id)
    )).all():
        add_party(holder, "account holder", acct)
        add_party(cp, "counterparty", acct)
    for cp, acct in (await db.execute(
        select(FraudCase.counterparty_name, FraudCase.account_id)
    )).all():
        add_party(cp, "counterparty", acct)

    # Token index so each subject is compared only against parties sharing a token.
    token_index: dict[str, set[str]] = {}
    for norm in parties:
        for tok in norm.split():
            token_index.setdefault(tok, set()).add(norm)

    matches = []
    for subject in subjects:
        q = S._normalize(subject)
        if not q:
            continue
        candidates: set[str] = set()
        for tok in q.split():
            candidates |= token_index.get(tok, set())
        best_norm, best_score = None, 0.0
        for cand in candidates:
            score = S._similarity(q, cand)
            if score >= body.threshold and score > best_score:
                best_norm, best_score = cand, score
        if best_norm:
            p = parties[best_norm]
            matches.append({
                "subject": subject,
                "matched_party": p["name"],
                "score": round(best_score, 3),
                "seen_as": sorted(p["roles"]),
                "occurrences": p["occurrences"],
                "account_ids": sorted(p["accounts"])[:10],
            })

    from backend.routers import audit as audit_router
    await audit_router.record(
        admin.username, "314A_SCAN",
        detail=f"subjects={len(subjects)}; parties_checked={len(parties)}; matches={len(matches)}",
    )
    return {
        "subjects_screened": len(subjects),
        "parties_checked": len(parties),
        "matches": matches,
        "note": "Screening aid only. Verify positive matches against customer records and respond "
                "via FinCEN's Secure Information Sharing System within the required window. "
                "FMS transmits nothing and does not store the subject list.",
    }


@router.get("/search")
async def search(q: str = Query(..., min_length=2, max_length=100),
                 db: AsyncSession = Depends(get_db),
                 _user: User = Depends(require_user)):
    """Global search across cases by account, counterparty, case id, or reference."""
    like = f"%{q}%"
    rows = (await db.execute(
        select(FraudCase)
        .where(
            FraudCase.account_id.like(like)
            | FraudCase.counterparty_name.like(like)
            | FraudCase.counterparty_account.like(like)
            | FraudCase.reference.like(like)
            | FraudCase.id.like(f"{q}%")
        )
        .order_by(FraudCase.created_at.desc())
        .limit(50)
    )).scalars().all()
    return {
        "query": q,
        "count": len(rows),
        "items": [
            {"id": c.id, "account_id": c.account_id, "amount": c.amount, "currency": c.currency,
             "direction": c.direction, "counterparty_name": c.counterparty_name,
             "fraud_type": c.fraud_type, "risk_score": c.risk_score, "status": c.status,
             "created_at": str(c.created_at)}
            for c in rows
        ],
    }


@router.get("/rules")
async def rules(_user: User = Depends(require_user)):
    """Transparent view of the detection engine's thresholds and scoring rules.
    Sourced from the analyzer so the page always reflects the live configuration."""
    return {
        "regulatory_thresholds": {
            "ctr_by_currency": A._CTR_THRESHOLDS,
            "sar_ratio_of_ctr": A.SAR_RATIO,
            "note": "CTR per FinCEN/BSA (USD $10,000). SAR threshold = CTR × ratio. "
                    "Structuring is reportable regardless of amount.",
        },
        "detection_parameters": {
            "structuring_band_ratio": A.STRUCTURING_BAND_RATIO,
            "rolling_window_days": A.ROLLING_WINDOW_DAYS,
            "smurfing_window_hours": A.SMURFING_WINDOW_HOURS,
        },
        "scoring_components": [
            {"name": "Behavioral deviation", "points": "0–35", "detail": "How far the amount sits from the account's own baseline (z-score bands)."},
            {"name": "High-value transfer", "points": "5–20", "detail": "Amount at/above the CTR threshold, scaled by how far above."},
            {"name": "Near-threshold amount", "points": "20", "detail": "Amount in the structuring band just below the reporting threshold."},
            {"name": "Velocity clustering", "points": "25", "detail": "Multiple sub-threshold transfers over the rolling window that together exceed it."},
            {"name": "Outward smurfing", "points": "20", "detail": "Same-counterparty same-day accumulation crossing the threshold."},
            {"name": "Multi-source smurfing", "points": "25", "detail": "3+ distinct senders in 48h whose combined inflow exceeds the threshold."},
            {"name": "New counterparty", "points": "6–12", "detail": "First transaction with this counterparty."},
            {"name": "Odd hours", "points": "8", "detail": "Transaction between 01:00 and 05:00."},
            {"name": "New channel", "points": "5", "detail": "Channel not previously used by the account."},
            {"name": "Same-day velocity", "points": "5–10", "detail": "Unusually many transactions on the same day."},
            {"name": "Batch/systematic payment", "points": "-20", "detail": "Payroll/batch reference or batch ID reduces suspicion."},
            {"name": "Established high-value pattern", "points": "-10", "detail": "Account with a consistent history of large transfers."},
        ],
        "risk_levels": [
            {"level": "LOW", "range": "0–30"},
            {"level": "MEDIUM", "range": "31–55"},
            {"level": "HIGH", "range": "56–75"},
            {"level": "CRITICAL", "range": "76–100"},
        ],
        "sanctions": {
            "list": "OFAC SDN + OFAC Consolidated non-SDN (+ optional PEP and institution-supplied lists)",
            "match_threshold": f"{S.DEFAULT_THRESHOLD:.2f} name-similarity",
            "note": "An SDN match overrides the behavioral score and forces a block/report case; "
                    "Consolidated/other-list matches raise a review-required case; PEP matches "
                    "annotate for enhanced due diligence.",
        },
        "national_priorities": {
            "note": "FinCEN National AML/CFT Priorities (June 30, 2021) and how this engine's "
                    "signals map to them. Coverage is stated honestly: FMS detects money-movement "
                    "mechanics and screens lists; predicate-crime attribution is always the "
                    "investigator's determination.",
            "items": NATIONAL_PRIORITIES,
        },
    }


# ─── Rule tuning: backtest + change history ───────────────────────────────────

class BacktestRequest(BaseModel):
    proposed: dict                 # same shape as the rules override (partial ok)
    days: int = 90                 # replay window
    limit: int = 5000              # cap on transactions replayed


def _replay(normalized: list) -> dict:
    """Replay the deterministic engine over the stored transactions under the
    CURRENT global parameters. History for each transaction = the prior
    transactions of the same account within the replay set (chronological)."""
    by_account: dict[str, list] = {}
    flagged = sar = ctr = 0
    verdicts = []
    for norm in normalized:
        history = by_account.setdefault(norm.account_id, [])
        v = A.evaluate(norm, list(history))
        verdicts.append(v)
        history.append(norm)
        if v["is_fraudulent"]:
            flagged += 1
        if v["sar_recommended"]:
            sar += 1
        if v["ctr"].required:
            ctr += 1
    return {"flagged": flagged, "sar_recommended": sar, "ctr_required": ctr, "verdicts": verdicts}


@router.post("/rules/backtest")
async def rules_backtest(
    body: BacktestRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """What would this parameter change have flagged historically? Replays the
    stored ingested transactions through the SAME deterministic engine under
    current vs. proposed parameters and reports the difference — evidence for
    the tuning log (FFIEC expects threshold changes to be assessed and
    documented). Read-only: proposed values are applied to the engine only for
    the duration of the replay, then restored."""
    from backend.routers.ingest import _to_normalized

    cutoff = datetime.utcnow() - timedelta(days=max(1, min(body.days, 365)))
    rows = (await db.execute(
        select(IngestedTransaction)
        .where(IngestedTransaction.timestamp >= cutoff)
        .order_by(IngestedTransaction.timestamp.desc())
        .limit(max(10, min(body.limit, 20_000)))
    )).scalars().all()
    rows = list(reversed(rows))  # chronological for coherent history replay
    if not rows:
        return {"error": "No ingested transactions in the replay window — nothing to backtest.",
                "replayed": 0}

    normalized = [_to_normalized(r) for r in rows]

    # The evaluate() loop is fully synchronous — no awaits between apply and
    # restore — so the temporary parameter swap can't leak into live requests
    # handled by this single-threaded event loop.
    current = _replay(normalized)
    snap = A.snapshot_rules()
    try:
        A.apply_rule_overrides(body.proposed or {})
        proposed = _replay(normalized)
    finally:
        A.restore_rules(snap)

    changed = []
    for row, norm, cur_v, new_v in zip(rows, normalized, current["verdicts"], proposed["verdicts"]):
        if (cur_v["is_fraudulent"], cur_v["sar_recommended"], cur_v["ctr"].required) != \
           (new_v["is_fraudulent"], new_v["sar_recommended"], new_v["ctr"].required):
            changed.append({
                "external_id": row.external_id,
                "account_id": norm.account_id,
                "amount": norm.amount,
                "currency": norm.currency,
                "timestamp": str(norm.timestamp),
                "current": {"flagged": cur_v["is_fraudulent"], "level": cur_v["risk"].level,
                            "sar": cur_v["sar_recommended"], "ctr": cur_v["ctr"].required},
                "proposed": {"flagged": new_v["is_fraudulent"], "level": new_v["risk"].level,
                             "sar": new_v["sar_recommended"], "ctr": new_v["ctr"].required},
            })
            if len(changed) >= 15:
                break

    def _summary(r: dict) -> dict:
        return {k: r[k] for k in ("flagged", "sar_recommended", "ctr_required")}

    return {
        "replayed": len(rows),
        "window_days": body.days,
        "note": "Replay of stored ingested transactions through the live deterministic engine. "
                "Account history is approximated within the replay window; sanctions screening "
                "and case creation are not part of a backtest.",
        "current": _summary(current),
        "proposed": _summary(proposed),
        "changed_examples": changed,
        "changed_count": sum(
            1 for c, p in zip(current["verdicts"], proposed["verdicts"])
            if (c["is_fraudulent"], c["sar_recommended"], c["ctr"].required)
            != (p["is_fraudulent"], p["sar_recommended"], p["ctr"].required)
        ),
    }


@router.get("/rules/changes")
async def rules_changes(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_user),
):
    """Tuning log: every detection-parameter change with before/after values,
    actor, rationale, and any backtest evidence attached at save time."""
    rows = (await db.execute(
        select(RuleChange).order_by(RuleChange.changed_at.desc()).limit(limit)
    )).scalars().all()
    return {
        "count": len(rows),
        "items": [
            {
                "id": r.id,
                "changed_by": r.changed_by,
                "changed_at": str(r.changed_at),
                "old_values": r.old_values,
                "new_values": r.new_values,
                "rationale": r.rationale,
                "backtest": r.backtest,
            }
            for r in rows
        ],
    }
