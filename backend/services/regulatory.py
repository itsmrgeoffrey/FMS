from dataclasses import dataclass
from datetime import datetime

from backend.adapters.base import NormalizedTransaction
from backend.services.risk_engine import RiskScoreResult
from backend.services.rules_config import SAR_RATIO


@dataclass
class CTRAssessment:
    required: bool
    reason: str               # human-readable explanation
    trigger: str              # SINGLE_TXN / SAME_DAY_AGGREGATE / NONE


# ─── SAR obligation assessment ────────────────────────────────────────────────
# Hard money-laundering signals (structuring / smurfing) are reportable on a SAR
# regardless of dollar amount — the pattern itself is the suspicious activity.
STRUCTURING_SIGNALS = frozenset(
    {"near_threshold_amount", "near_miss_spike", "velocity_clustering",
     "outward_smurfing", "multi_source_smurfing"}
)


def assess_ctr(
    txn: NormalizedTransaction,
    history: list[NormalizedTransaction],
    threshold: float,
) -> CTRAssessment:
    if txn.amount >= threshold:
        return CTRAssessment(
            required=True,
            reason=f"Single transaction of {txn.currency} {txn.amount:,.2f} exceeds CTR threshold",
            trigger="SINGLE_TXN",
        )

    today = txn.timestamp.date() if isinstance(txn.timestamp, datetime) else None
    if today:
        same_day = [
            h for h in history
            if isinstance(h.timestamp, datetime)
            and h.timestamp.date() == today
            and h.direction == txn.direction
        ]
        day_total = sum(h.amount for h in same_day) + txn.amount
        if day_total >= threshold:
            return CTRAssessment(
                required=True,
                reason=(
                    f"Same-direction day aggregate: {txn.currency} {day_total:,.2f} "
                    f"across {len(same_day) + 1} transactions"
                ),
                trigger="SAME_DAY_AGGREGATE",
            )

    return CTRAssessment(required=False, reason="", trigger="NONE")


def assess_sar(
    txn: NormalizedTransaction,
    risk: RiskScoreResult,
    is_fraudulent: bool,
    ctr_threshold: float,
) -> tuple[bool, str]:
    """Recommend a Suspicious Activity Report when the flagged activity meets the
    BSA reporting bar: structuring/smurfing (any amount) or a suspicious amount
    at/above the SAR threshold (half the CTR threshold)."""
    if not is_fraudulent:
        return False, ""

    cur = txn.currency
    structuring = STRUCTURING_SIGNALS & risk.components.keys()
    if structuring:
        return True, (
            f"Potential structuring/smurfing pattern detected "
            f"({', '.join(sorted(structuring))}) — reportable on a SAR regardless of amount."
        )

    sar_threshold = ctr_threshold * SAR_RATIO
    # Largest suspicious amount in play: the transaction itself or a suspicious aggregate.
    involved = max(
        txn.amount,
        risk.rolling_5d_total if risk.rolling_5d_count > 1 else 0.0,
        risk.inbound_total_48h,
    )
    if involved >= sar_threshold:
        return True, (
            f"Suspicious activity involving {cur} {involved:,.2f} meets the "
            f"{cur} {sar_threshold:,.0f} SAR reporting threshold — recommend filing a "
            f"Suspicious Activity Report."
        )
    return False, ""