import json
import logging

from backend.adapters.base import NormalizedTransaction
from backend.config import settings
from backend.services.llm_client import generate_summary_text
from backend.services.profiler import BehavioralProfile
from backend.services.regulatory import CTRAssessment
from backend.services.risk_engine import RiskScoreResult

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You write plain-English fraud alert summaries for bank compliance officers. "
    "2–3 sentences only. No jargon, no scores, no internal system names. "
    "Focus on behaviour: what this account normally does, what this transaction does differently, "
    "and what the officer should do next. "
    "If a CTR filing is noted, mention it as a regulatory requirement — not as evidence of fraud. "
    "Respond with valid JSON only. No markdown."
)


def fallback_summary(
    txn: NormalizedTransaction,
    risk: RiskScoreResult,
    profile: BehavioralProfile,
    reasons: list[str],
    ctr: CTRAssessment,
) -> str:
    """Build a plain-English summary without the LLM, so an outage never blocks
    a case from being created. Uses the already-computed deterministic reasons."""
    cur = txn.currency
    if profile.transaction_count > 0 and profile.avg_amount > 0:
        opener = (
            f"This account typically transfers around {cur} {profile.avg_amount:,.0f}; "
            f"this {cur} {txn.amount:,.2f} {txn.direction.lower()} transaction stands out. "
        )
    else:
        opener = f"This {cur} {txn.amount:,.2f} {txn.direction.lower()} transaction was flagged for review. "
    body = " ".join(reasons[:2])
    action = " A compliance officer should review the account and confirm or dismiss the alert."
    if ctr.required:
        action += " A CTR filing is also required (a separate regulatory obligation)."
    return (opener + body + action).strip()


async def build_summary(
    txn: NormalizedTransaction,
    risk: RiskScoreResult,
    profile: BehavioralProfile,
    reasons: list[str],
    ctr: CTRAssessment,
) -> str:
    """Build summary using LLM if enabled, otherwise use deterministic fallback."""
    reasons_text = "\n".join(f"- {r}" for r in reasons)

    # Structured delta report — gives the AI the specific numbers so its explanation
    # references actual values, not generic phrases.
    if profile.transaction_count > 0:
        amount_multiple = txn.amount / profile.avg_amount if profile.avg_amount > 0 else 0
        cp_status = "(NEW — never seen before)" if "new_counterparty" in risk.components else "(known counterparty)"
        ch_status = "(NEW — never used before)" if "new_channel" in risk.components else ""
        t_status = "(unusual hours — 01:00–04:00)" if "odd_hours" in risk.components else ""
        delta_block = (
            f"ACCOUNT BASELINE (last 90 days, {profile.transaction_count} transactions):\n"
            f"  Typical amount    : {txn.currency} {profile.avg_amount:,.0f}\n"
            f"  Historical max    : {txn.currency} {profile.max_amount:,.0f}\n"
            f"  Known counterparties : {profile.known_counterparties}\n\n"
            f"THIS TRANSACTION:\n"
            f"  Amount  : {txn.currency} {txn.amount:,.2f}  ({amount_multiple:.1f}x the account average)\n"
            f"  To      : {txn.counterparty_name or txn.counterparty_account or 'unknown'}  {cp_status}\n"
            f"  Channel : {txn.channel or 'unknown'}  {ch_status}\n"
            f"  Time    : {txn.timestamp.strftime('%H:%M') if isinstance(txn.timestamp, __import__('datetime').datetime) else 'unknown'}  {t_status}"
        )
    else:
        delta_block = (
            f"ACCOUNT BASELINE: No prior transaction history.\n\n"
            f"THIS TRANSACTION:\n"
            f"  Amount  : {txn.currency} {txn.amount:,.2f}\n"
            f"  To      : {txn.counterparty_name or txn.counterparty_account or 'unknown'}\n"
            f"  Channel : {txn.channel or 'unknown'}\n"
            f"  Time    : {txn.timestamp.strftime('%H:%M') if isinstance(txn.timestamp, __import__('datetime').datetime) else 'unknown'}"
        )

    ctr_note = (
        f"\nREGULATORY NOTE: {ctr.reason} — CTR filing required (separate regulatory obligation, not evidence of fraud)."
        if ctr.required else ""
    )

    summary_prompt = f"""You are writing a fraud alert summary for a bank compliance officer.

{delta_block}{ctr_note}

FLAGS RAISED:
{reasons_text}

Write 2-3 plain-English sentences that:
1. State what this account normally does (use the baseline numbers above)
2. State exactly what is different about this transaction (use the delta numbers)
3. Tell the officer what action to take

No jargon. No scores. No internal system names. Use the actual numbers from the delta report.

Respond with ONLY this JSON:
{{"summary": "your 2-3 sentence explanation here"}}"""

    # AI summaries are opt-in (FMS_AI_SUMMARIES). By DEFAULT the deterministic
    # engine writes the summary and no transaction data leaves the host. When
    # enabled, the LLM only produces the human-readable prose — it never
    # influences whether a case is raised (that is all computed above).
    summary = ""
    if settings.ai_summaries.strip().lower() in ("on", "true", "1", "yes"):
        try:
            raw = await generate_summary_text(SYSTEM_PROMPT, summary_prompt)
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            try:
                summary = json.loads(raw).get("summary", "") or raw
            except Exception:
                summary = raw
        except Exception as e:
            log.warning(f"LLM summary unavailable ({e}) — using deterministic fallback")

    if not summary:
        summary = fallback_summary(txn, risk, profile, reasons, ctr)

    return summary


def format_history(txns: list[NormalizedTransaction]) -> str:
    if not txns:
        return "No prior transactions found."
    lines = ["Timestamp              | Dir     | Amount        | Counterparty           | Channel"]
    lines.append("-" * 90)
    for t in txns[:50]:
        lines.append(
            f"{str(t.timestamp)[:19]:<22}| {t.direction:<8}| "
            f"{t.currency} {t.amount:>12,.2f} | {(t.counterparty_name or 'Unknown'):<22} | {t.channel or '-'}"
        )
    return "\n".join(lines)