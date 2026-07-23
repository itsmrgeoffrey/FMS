import logging
from dataclasses import dataclass

from backend.adapters.base import NormalizedTransaction
from backend.config import bank_config, settings
from backend.services import sanctions
from backend.services.llm_client import get_client, reset_client, generate_summary_text
from backend.services.profiler import BehavioralProfile, compute_behavioral_profile
from backend.services.regulatory import CTRAssessment, assess_ctr, assess_sar
from backend.services.reason_generator import pick_fraud_type, plain_reasons
from backend.services.risk_engine import RiskScoreResult, compute_risk_score
from backend.services.rules_config import (
    apply_rule_overrides, snapshot_rules, restore_rules,
    ctr_threshold, sar_threshold, detect_batch,
    ROLLING_WINDOW_DAYS, SMURFING_WINDOW_HOURS, STRUCTURING_BAND_RATIO,
    CTR_THRESHOLDS, SAR_RATIO, BATCH_PATTERN,
)
from backend.services.summary_builder import build_summary, fallback_summary, format_history

log = logging.getLogger(__name__)

# Re-export for backwards compatibility
_client = None
_CTR_THRESHOLDS = CTR_THRESHOLDS  # Original had underscore prefix


def _get_client():
    """Construct the Groq client lazily so importing this module (e.g. in tests)
    doesn't require an API key — only generating a summary does."""
    global _client
    if _client is None:
        _client = get_client()
    return _client


def _reset_client():
    """Reset the LLM client (called when API key changes)."""
    global _client
    _client = None
    reset_client()


@dataclass
class FraudAnalysis:
    is_fraudulent: bool
    confidence: str
    fraud_type: str | None
    reasons: list
    summary: str
    risk_score: int
    ctr_required: bool
    ctr_reason: str
    sar_recommended: bool = False
    sar_reason: str = ""
    sanctions_hit: bool = False
    sanctions_detail: str = ""


# ─── Deterministic verdict core ──────────────────────────────────────────────
# The complete rules-only evaluation (no sanctions screening, no LLM). analyze()
# builds on this, and rule backtesting replays it over stored history — one code
# path, so a backtest result is exactly what the live engine would have done.

HARD_FRAUD_SIGNALS = frozenset(
    {"near_threshold_amount", "velocity_clustering", "outward_smurfing", "multi_source_smurfing"}
)


def evaluate(txn: NormalizedTransaction, history: list[NormalizedTransaction]) -> dict:
    threshold = ctr_threshold(txn.currency)
    profile = compute_behavioral_profile(history, threshold)
    ctr = assess_ctr(txn, history, threshold)
    risk = compute_risk_score(txn, history, profile, threshold)

    has_hard_signal = bool(HARD_FRAUD_SIGNALS & risk.components.keys())
    if risk.level == "LOW" and not has_hard_signal:
        is_fraudulent, confidence = False, "LOW"
    elif risk.level == "MEDIUM":
        is_fraudulent, confidence = True, "MEDIUM"
    else:
        is_fraudulent, confidence = True, "HIGH"

    sar_recommended, sar_reason = assess_sar(txn, risk, is_fraudulent, threshold)
    return {
        "threshold": threshold, "profile": profile, "ctr": ctr, "risk": risk,
        "is_fraudulent": is_fraudulent, "confidence": confidence,
        "sar_recommended": sar_recommended, "sar_reason": sar_reason,
    }


# ─── Main entry point ─────────────────────────────────────────────────────────

async def analyze(txn: NormalizedTransaction, history: list[NormalizedTransaction]) -> FraudAnalysis:
    verdict = evaluate(txn, history)
    threshold, profile, ctr, risk = verdict["threshold"], verdict["profile"], verdict["ctr"], verdict["risk"]
    is_fraudulent, confidence = verdict["is_fraudulent"], verdict["confidence"]
    sar_recommended, sar_reason = verdict["sar_recommended"], verdict["sar_reason"]

    # Reasons are generated deterministically — no hallucination risk
    reasons = plain_reasons(txn, risk, profile, ctr, threshold)

    fraud_type = pick_fraud_type(risk) if is_fraudulent else None

    # OFAC sanctions screening overrides the behavioural score: a listed
    # counterparty is a block/report obligation regardless of risk level.
    # PEP matches are different in kind — enhanced due diligence, not blocking —
    # so they annotate the case instead of overriding it.
    sanctions_match = sanctions.screen(txn.counterparty_name)
    sanctions_hit = sanctions_match is not None and sanctions_match.list_type == "SDN"
    sanctions_detail = ""
    if sanctions_match and sanctions_match.list_type == "SDN":
        sanctions_detail = (
            f"Counterparty '{sanctions_match.query}' matches {sanctions_match.source} "
            f"entry '{sanctions_match.matched_name}' "
            f"(program: {sanctions_match.program or 'N/A'}, {sanctions_match.score:.0%} match)"
        )
        is_fraudulent = True
        confidence = "HIGH"
        fraud_type = "sanctions match"
        reasons = [
            f"OFAC SANCTIONS MATCH — {sanctions_detail}. This is a listed party: the "
            f"transaction must be blocked or rejected and reported to OFAC. Escalate to "
            f"your BSA/AML officer immediately."
        ] + reasons
    elif sanctions_match and sanctions_match.list_type == "PEP":
        reasons = [
            f"POLITICALLY EXPOSED PERSON — counterparty '{sanctions_match.query}' matches "
            f"{sanctions_match.source} entry '{sanctions_match.matched_name}' "
            f"({sanctions_match.score:.0%} match). Not a blocking obligation, but enhanced "
            f"due diligence is expected for PEP-linked transactions."
        ] + reasons
    elif sanctions_match:  # NON_SDN (OFAC Consolidated) or an institution-supplied list
        is_fraudulent = True
        confidence = "HIGH"
        fraud_type = "watch-list match"
        reasons = [
            f"WATCH-LIST MATCH (review required) — counterparty '{sanctions_match.query}' matches "
            f"{sanctions_match.source} entry '{sanctions_match.matched_name}' "
            f"(program: {sanctions_match.program or 'N/A'}, {sanctions_match.score:.0%} match). "
            f"Non-SDN lists carry program-specific restrictions rather than a blanket block "
            f"obligation — review the listed program's requirements before processing."
        ] + reasons

    summary = await build_summary(txn, risk, profile, reasons, ctr)

    return FraudAnalysis(
        is_fraudulent=is_fraudulent,
        confidence=confidence,
        fraud_type=fraud_type,
        reasons=reasons,
        summary=summary,
        risk_score=risk.score,
        ctr_required=ctr.required,
        ctr_reason=ctr.reason,
        sar_recommended=sar_recommended,
        sar_reason=sar_reason,
        sanctions_hit=sanctions_hit,
        sanctions_detail=sanctions_detail,
    )


# Apply operator-tuned rule overrides persisted in bank_config.yaml.
apply_rule_overrides(bank_config.get("rules", {}) or {})