import json
import logging
import re
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from groq import AsyncGroq
from backend.adapters.base import NormalizedTransaction
from backend.config import settings

log = logging.getLogger(__name__)

_client: AsyncGroq | None = None


def _get_client() -> AsyncGroq:
    """Construct the Groq client lazily so importing this module (e.g. in tests)
    doesn't require an API key — only generating a summary does."""
    global _client
    if _client is None:
        _client = AsyncGroq(api_key=settings.groq_api_key)
    return _client

# ─── Currency-aware CTR thresholds ────────────────────────────────────────────
# Cash-transaction reporting threshold. In the US this is the FinCEN / Bank
# Secrecy Act CTR threshold (USD 10,000, per 31 CFR 1010.311). Other rows are
# the local-currency equivalents for jurisdictions we've onboarded.
# Add currencies here as new bank configs are onboarded.
_CTR_THRESHOLDS: dict[str, float] = {
    "USD": 10_000,
    "NGN": 15_000_000,   # ~$10k at ≈1,500 NGN/USD
    "GBP": 8_000,
    "EUR": 9_000,
    "CAD": 13_500,
    "AUD": 15_000,
    "GHS": 120_000,      # Ghana cedis ~$10k
    "ZAR": 190_000,      # South African rand ~$10k
}

# Suspicious Activity Report (SAR) threshold. Under the BSA a bank must file a
# SAR for suspicious activity aggregating to USD 5,000 or more when a suspect
# can be identified (31 CFR 1020.320) — half the CTR threshold. Structuring is
# reportable regardless of amount, which _assess_sar() handles separately.
SAR_RATIO = 0.5

ROLLING_WINDOW_DAYS = 5
SMURFING_WINDOW_HOURS = 48
STRUCTURING_BAND_RATIO = 0.9   # bottom of near-threshold band = 90% of high-value threshold

# Reference text patterns that indicate a scheduled/systematic/batch payment.
# If the transaction's reference OR batch_id matches, the engine reduces suspicion
# before applying behavioural checks — bulk payroll or supplier runs should not
# score the same as a one-off transfer to an unknown counterparty.
_BATCH_PATTERN = re.compile(
    r"\b(batch|payroll|pay[\s\-]?run|salary|salaries|wages|bulk|sweep|"
    r"standing[\s\-]?order|scheduled|auto[\s\-]?debit|direct[\s\-]?debit|"
    r"regular[\s\-]?payment|monthly[\s\-]?payment|quarterly|disbursement)\b",
    re.IGNORECASE,
)


def _ctr_threshold(currency: str) -> float:
    return _CTR_THRESHOLDS.get((currency or "USD").upper(), 10_000)


def _sar_threshold(currency: str) -> float:
    return _ctr_threshold(currency) * SAR_RATIO


def _detect_batch(txn: NormalizedTransaction) -> str | None:
    """Return the batch identifier if the transaction looks like a systematic payment, else None."""
    if txn.batch_id:
        return txn.batch_id
    if txn.reference and _BATCH_PATTERN.search(txn.reference):
        return txn.reference
    return None


SYSTEM_PROMPT = (
    "You write plain-English fraud alert summaries for bank compliance officers. "
    "2–3 sentences only. No jargon, no scores, no internal system names. "
    "Focus on behaviour: what this account normally does, what this transaction does differently, "
    "and what the officer should do next. "
    "If a CTR filing is noted, mention it as a regulatory requirement — not as evidence of fraud. "
    "Respond with valid JSON only. No markdown."
)


def _pick_fraud_type(risk: "RiskScoreResult") -> str | None:
    c = risk.components
    if "multi_source_smurfing" in c:
        return "multi-source smurfing"
    if "outward_smurfing" in c:
        return "outward smurfing"
    if "velocity_clustering" in c and "new_counterparty" in c:
        return "velocity clustering"
    if "near_threshold_amount" in c:
        return "near-threshold pattern"
    # Account takeover: established account suddenly uses a new channel or odd hours with unknown recipient
    if (
        "behavioral_deviation" in c
        and "new_counterparty" in c
        and ("new_channel" in c or "odd_hours" in c)
    ) or ("new_account_risk" in c and "high_value_transfer" in c):
        return "account takeover"
    # Invoice fraud: established account, large unexpected payment to a new vendor
    if "behavioral_deviation" in c and "new_counterparty" in c:
        return "invoice fraud"
    if "odd_hours" in c and "new_counterparty" in c:
        return "suspicious timing"
    if "high_value_transfer" in c and "new_counterparty" in c:
        return "suspicious large payment"
    if "high_value_transfer" in c:
        return "large outward transfer"
    if risk.score > 30:
        return "unusual transfer"
    return None


@dataclass
class BehavioralProfile:
    transaction_count: int
    avg_amount: float
    max_amount: float
    std_dev: float
    ctr_level_count: int      # prior single txns >= CTR threshold for this currency
    large_txn_pct: float      # % of txns > 50% of CTR threshold
    known_counterparties: int
    active_channels: list
    days_active: int
    recent_7d_count: int


@dataclass
class CTRAssessment:
    required: bool
    reason: str               # human-readable explanation
    trigger: str              # SINGLE_TXN / SAME_DAY_AGGREGATE / NONE


@dataclass
class RiskScoreResult:
    score: int                # 0-100
    level: str                # LOW / MEDIUM / HIGH / CRITICAL
    behavioral_verdict: str   # CONSISTENT / UNUSUAL / ANOMALOUS / NEW_ACCOUNT
    components: dict
    rolling_5d_total: float
    rolling_5d_count: int
    inbound_sources_48h: int
    inbound_total_48h: float


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


# ─── CTR obligation assessment ────────────────────────────────────────────────

def _assess_ctr(
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


# ─── SAR obligation assessment ────────────────────────────────────────────────
# Hard money-laundering signals (structuring / smurfing) are reportable on a SAR
# regardless of dollar amount — the pattern itself is the suspicious activity.
_STRUCTURING_SIGNALS = frozenset(
    {"near_threshold_amount", "near_miss_spike", "velocity_clustering",
     "outward_smurfing", "multi_source_smurfing"}
)


def _assess_sar(
    txn: NormalizedTransaction,
    risk: "RiskScoreResult",
    is_fraudulent: bool,
    ctr_threshold: float,
) -> tuple[bool, str]:
    """Recommend a Suspicious Activity Report when the flagged activity meets the
    BSA reporting bar: structuring/smurfing (any amount) or a suspicious amount
    at/above the SAR threshold (half the CTR threshold)."""
    if not is_fraudulent:
        return False, ""

    cur = txn.currency
    structuring = _STRUCTURING_SIGNALS & risk.components.keys()
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


# ─── Rolling window helpers ───────────────────────────────────────────────────

def _rolling_window(
    txn: NormalizedTransaction,
    history: list[NormalizedTransaction],
    days: int = ROLLING_WINDOW_DAYS,
) -> tuple[float, int]:
    """Total same-direction amount for this account in the last N days (including current txn)."""
    if not isinstance(txn.timestamp, datetime):
        return txn.amount, 1
    cutoff = txn.timestamp - timedelta(days=days)
    window = [
        h for h in history
        if isinstance(h.timestamp, datetime)
        and h.timestamp >= cutoff
        and h.direction == txn.direction
    ]
    return round(sum(h.amount for h in window) + txn.amount, 2), len(window) + 1


def _inbound_sources(
    txn: NormalizedTransaction,
    history: list[NormalizedTransaction],
    hours: int = SMURFING_WINDOW_HOURS,
) -> tuple[int, float]:
    """For INWARD txns: (distinct senders, total received) in the last N hours."""
    if txn.direction != "INWARD" or not isinstance(txn.timestamp, datetime):
        return 0, 0.0
    cutoff = txn.timestamp - timedelta(hours=hours)
    recent = [
        h for h in history
        if h.direction == "INWARD"
        and isinstance(h.timestamp, datetime)
        and h.timestamp >= cutoff
    ]
    senders = {h.counterparty_account for h in recent if h.counterparty_account}
    if txn.counterparty_account:
        senders.add(txn.counterparty_account)
    total = round(sum(h.amount for h in recent) + txn.amount, 2)
    return len(senders), total


# ─── Behavioral profile ───────────────────────────────────────────────────────

def _compute_behavioral_profile(
    history: list[NormalizedTransaction],
    threshold: float,
) -> BehavioralProfile:
    if not history:
        return BehavioralProfile(
            transaction_count=0, avg_amount=0.0, max_amount=0.0, std_dev=0.0,
            ctr_level_count=0, large_txn_pct=0.0, known_counterparties=0,
            active_channels=[], days_active=0, recent_7d_count=0,
        )
    amounts = [h.amount for h in history]
    avg = statistics.mean(amounts)
    std = statistics.stdev(amounts) if len(amounts) > 1 else 0.0
    cutoff = datetime.utcnow() - timedelta(days=7)
    return BehavioralProfile(
        transaction_count=len(history),
        avg_amount=round(avg, 2),
        max_amount=max(amounts),
        std_dev=round(std, 2),
        ctr_level_count=sum(1 for a in amounts if a >= threshold),
        large_txn_pct=round(sum(1 for a in amounts if a >= threshold * 0.5) / len(amounts) * 100, 1),
        known_counterparties=len({h.counterparty_account for h in history if h.counterparty_account}),
        active_channels=list({h.channel for h in history if h.channel}),
        days_active=len({h.timestamp.date() for h in history if isinstance(h.timestamp, datetime)}),
        recent_7d_count=sum(1 for h in history if isinstance(h.timestamp, datetime) and h.timestamp >= cutoff),
    )


# ─── Risk scoring ─────────────────────────────────────────────────────────────

def _compute_risk_score(
    txn: NormalizedTransaction,
    history: list[NormalizedTransaction],
    profile: BehavioralProfile,
    threshold: float,
) -> RiskScoreResult:
    score = 0
    components: dict = {}
    behavioral_verdict = "CONSISTENT"

    structuring_low = threshold * STRUCTURING_BAND_RATIO
    structuring_high = threshold - 1  # one unit below threshold

    rolling_total, rolling_count = _rolling_window(txn, history)
    src_count_48h, inbound_total_48h = _inbound_sources(txn, history)

    # ── 0. Batch / systematic payment signal (-20) ────────────────────────────
    # Check for a batch ID or reference pattern BEFORE applying behavioural checks.
    # A payroll run or supplier batch should not score the same as a one-off transfer
    # to an unknown counterparty just because the amount is large.
    batch_ref = _detect_batch(txn)
    if batch_ref:
        components["batch_payment"] = {
            "score": -20,
            "reason": f"Transaction carries a systematic/batch payment reference: '{batch_ref}'",
        }
        score -= 20

    # ── 1. Behavioral deviation: how far is this from the account's norm (0-35) ──
    if profile.transaction_count == 0:
        dev_pts = 20 if txn.amount >= threshold * 0.5 else 10
        behavioral_verdict = "NEW_ACCOUNT"
        components["new_account_risk"] = {
            "score": dev_pts,
            "reason": "No prior transaction history — flagged as first-time activity on a new or unseasoned account",
        }
    else:
        z = (
            (txn.amount - profile.avg_amount) / profile.std_dev
            if profile.std_dev > 0
            else (5.0 if txn.amount > profile.avg_amount else 0.0)
        )
        if z <= 1:
            dev_pts, behavioral_verdict = 0, "CONSISTENT"
        elif z <= 2:
            dev_pts, behavioral_verdict = 10, "UNUSUAL"
        elif z <= 3:
            dev_pts, behavioral_verdict = 22, "UNUSUAL"
        else:
            dev_pts, behavioral_verdict = 35, "ANOMALOUS"

        if dev_pts > 0:
            components["behavioral_deviation"] = {
                "score": dev_pts,
                "reason": (
                    f"This amount is much larger than what this account normally sends "
                    f"(typical transaction: {txn.currency} {profile.avg_amount:,.0f})"
                ),
            }

        # Established large-transfer pattern reduces suspicion — but NOT when the amount
        # is so far outside the norm that we've already called it ANOMALOUS.
        # An account that always does $50k and suddenly does $425k is MORE suspicious,
        # not less, because the deviation can't be explained by "they do big transfers."
        if profile.ctr_level_count >= 3 and behavioral_verdict not in ("ANOMALOUS", "NEW_ACCOUNT"):
            score -= 10
            components["established_high_value_pattern"] = {
                "score": -10,
                "reason": (
                    f"Account has {profile.ctr_level_count} prior CTR-level transactions"
                    " — consistent behaviour pattern for this account"
                ),
            }

    score += dev_pts

    # ── 2. High-value transfer (5-20) ────────────────────────────────────────
    if txn.amount >= threshold:
        excess = txn.amount - threshold
        excess_ratio = excess / threshold
        hv_pts = (
            5 if excess_ratio < 0.5
            else 10 if excess_ratio < 1.5
            else 15 if excess_ratio < 4
            else 20
        )
        components["high_value_transfer"] = {
            "score": hv_pts,
            "reason": (
                f"Transfer of {txn.currency} {txn.amount:,.2f} is significantly above "
                f"the {txn.currency} {threshold:,.0f} high-value threshold"
            ),
        }
        score += hv_pts

    # ── 3. Near-threshold amount (20) ────────────────────────────────────────
    if structuring_low <= txn.amount <= structuring_high:
        components["near_threshold_amount"] = {
            "score": 20,
            "reason": (
                f"Amount {txn.currency} {txn.amount:,.2f} falls just below the "
                f"{txn.currency} {threshold:,.0f} reporting threshold "
                f"(band: {txn.currency} {structuring_low:,.0f}–{structuring_high:,.0f})"
            ),
        }
        score += 20

    # ── 4. Velocity clustering — rolling 5-day window (25) ───────────────────
    if (
        rolling_total >= threshold
        and txn.amount < threshold
        and rolling_count >= 2
    ):
        components["velocity_clustering"] = {
            "score": 25,
            "reason": (
                f"{rolling_count} same-direction transactions over {ROLLING_WINDOW_DAYS} days "
                f"total {txn.currency} {rolling_total:,.2f} — high transfer frequency "
                f"with no single transaction crossing the reporting threshold"
            ),
        }
        score += 25

    # ── 5. Outward same-counterparty day accumulation / classic smurfing (20) ─
    today = txn.timestamp.date() if isinstance(txn.timestamp, datetime) else None
    known_cps = {h.counterparty_account for h in history if h.counterparty_account}
    is_new_cp = txn.counterparty_account not in known_cps

    if today and txn.counterparty_account and txn.direction == "OUTWARD":
        cp_today = [
            h for h in history
            if h.counterparty_account == txn.counterparty_account
            and isinstance(h.timestamp, datetime)
            and h.timestamp.date() == today
            and h.direction == "OUTWARD"
        ]
        cp_day_total = sum(h.amount for h in cp_today) + txn.amount
        if cp_day_total >= threshold and cp_today:
            components["outward_smurfing"] = {
                "score": 20,
                "reason": (
                    f"Cumulative outward to same counterparty today: "
                    f"{txn.currency} {cp_day_total:,.2f} across {len(cp_today) + 1} transactions"
                ),
            }
            score += 20

    # ── 6. Multi-source inward smurfing (25) ─────────────────────────────────
    if (
        src_count_48h >= 3
        and inbound_total_48h >= threshold
        and txn.direction == "INWARD"
    ):
        components["multi_source_smurfing"] = {
            "score": 25,
            "reason": (
                f"{src_count_48h} different accounts deposited into this account in the last "
                f"{SMURFING_WINDOW_HOURS}h; combined inflow: {txn.currency} {inbound_total_48h:,.2f}"
            ),
        }
        score += 25

    # ── 7. Repeated near-threshold amounts in recent history (10) ────────────
    if not (structuring_low <= txn.amount <= structuring_high):
        cutoff5 = txn.timestamp - timedelta(days=ROLLING_WINDOW_DAYS) if isinstance(txn.timestamp, datetime) else None
        if cutoff5:
            near_miss_in_window = [
                h for h in history
                if structuring_low <= h.amount <= structuring_high
                and isinstance(h.timestamp, datetime)
                and h.timestamp >= cutoff5
            ]
            if len(near_miss_in_window) >= 2:
                components["near_miss_spike"] = {
                    "score": 10,
                    "reason": (
                        f"{len(near_miss_in_window)} recent transactions in the near-threshold band "
                        f"({txn.currency} {structuring_low:,.0f}–{structuring_high:,.0f}) "
                        f"in the last {ROLLING_WINDOW_DAYS} days"
                    ),
                }
                score += 10

    # ── 8. New counterparty (6-12) ────────────────────────────────────────────
    if is_new_cp and txn.counterparty_account:
        cp_pts = 12 if txn.amount >= threshold else 6
        components["new_counterparty"] = {
            "score": cp_pts,
            "reason": "Counterparty has never appeared in this account's transaction history",
        }
        score += cp_pts

    # ── 9. Odd hours (8) ──────────────────────────────────────────────────────
    hour = txn.timestamp.hour if isinstance(txn.timestamp, datetime) else 12
    if hour in range(1, 5):
        components["odd_hours"] = {
            "score": 8,
            "reason": f"Transaction submitted at {hour:02d}:00 (between 1 am and 4 am)",
        }
        score += 8

    # ── 10. New channel (5) ────────────────────────────────────────────────────
    if txn.channel and txn.channel not in profile.active_channels:
        components["new_channel"] = {
            "score": 5,
            "reason": f"Channel '{txn.channel}' has not been used by this account before",
        }
        score += 5

    # ── 11. Same-day velocity (5-10) ──────────────────────────────────────────
    if today:
        todays = [h for h in history if isinstance(h.timestamp, datetime) and h.timestamp.date() == today]
        if len(todays) >= 5:
            components["high_velocity"] = {
                "score": 10,
                "reason": f"{len(todays)} other transactions already today — unusually high velocity",
            }
            score += 10
        elif len(todays) >= 3:
            components["elevated_velocity"] = {
                "score": 5,
                "reason": f"{len(todays)} other transactions today",
            }
            score += 5

    score = max(0, min(100, score))

    if score <= 30:
        level = "LOW"
    elif score <= 55:
        level = "MEDIUM"
    elif score <= 75:
        level = "HIGH"
    else:
        level = "CRITICAL"

    return RiskScoreResult(
        score=score, level=level,
        behavioral_verdict=behavioral_verdict,
        components=components,
        rolling_5d_total=rolling_total,
        rolling_5d_count=rolling_count,
        inbound_sources_48h=src_count_48h,
        inbound_total_48h=inbound_total_48h,
    )


# ─── Plain-English reason templates (no AI needed — deterministic) ────────────

def _plain_reasons(
    txn: NormalizedTransaction,
    risk: RiskScoreResult,
    profile: BehavioralProfile,
    ctr: CTRAssessment,
    threshold: float,
) -> list[str]:
    c = risk.components
    cur = txn.currency
    reasons = []

    if "batch_payment" in c:
        batch_ref_label = c["batch_payment"]["reason"].split(": ", 1)[-1].strip("'")
        reasons.append(
            f"This transaction carries a systematic payment reference ({batch_ref_label}) "
            f"— consistent with a scheduled or batch payment run."
        )

    if "new_account_risk" in c:
        reasons.append(
            "This account has no previous transaction history — "
            "this is first-time activity on a new or unseasoned account."
        )

    if "behavioral_deviation" in c:
        reasons.append(
            f"This transfer of {cur} {txn.amount:,.2f} is far outside what this account "
            f"normally sends — their typical transfer is around {cur} {profile.avg_amount:,.0f}."
        )

    if "established_high_value_pattern" in c:
        reasons.append(
            f"This account regularly sends large amounts — they have made {profile.ctr_level_count} "
            f"high-value transfers before, so large transfers are consistent with their profile."
        )

    if "high_value_transfer" in c:
        reasons.append(
            f"This transfer of {cur} {txn.amount:,.2f} is significantly above the "
            f"{cur} {threshold:,.0f} high-value threshold."
        )

    if "near_threshold_amount" in c:
        reasons.append(
            f"The amount ({cur} {txn.amount:,.2f}) sits just below the {cur} {threshold:,.0f} "
            f"reporting threshold — a pattern of multiple such amounts could indicate deliberate splitting."
        )

    if "velocity_clustering" in c:
        reasons.append(
            f"This account made {risk.rolling_5d_count} transfers over the past 5 days "
            f"totalling {cur} {risk.rolling_5d_total:,.2f}, with no single transfer crossing "
            f"the {cur} {threshold:,.0f} threshold — the overall volume is unusually high."
        )

    if "outward_smurfing" in c:
        reasons.append(
            f"Multiple payments were sent to the same recipient today, "
            f"each below {cur} {threshold:,.0f}, but adding up to more than the reporting threshold."
        )

    if "multi_source_smurfing" in c:
        reasons.append(
            f"{risk.inbound_sources_48h} different accounts have deposited money into this account "
            f"in the last 48 hours, totalling {cur} {risk.inbound_total_48h:,.2f} — "
            f"this pattern of multiple small deposits from different senders is known as smurfing."
        )

    if "near_miss_spike" in c:
        reasons.append(
            f"Several recent transactions from this account clustered just below the "
            f"{cur} {threshold:,.0f} threshold — an unusual pattern worth reviewing."
        )

    if "new_counterparty" in c:
        name = txn.counterparty_name or txn.counterparty_account or "the recipient"
        reasons.append(f"{name} has never received a payment from this account before.")

    if "odd_hours" in c:
        hour = txn.timestamp.hour if isinstance(txn.timestamp, datetime) else 0
        reasons.append(f"This transfer was made at {hour:02d}:00 in the early hours of the morning.")

    if "new_channel" in c:
        reasons.append(
            f"This account has never used {txn.channel} to make transfers before — "
            f"a sudden change in how an account sends money can indicate the account has been compromised."
        )

    if "high_velocity" in c or "elevated_velocity" in c:
        reasons.append("This account has made an unusually high number of transactions today.")

    return reasons or ["No specific fraud signals were detected for this transaction."]


# ─── Deterministic fallback summary (used when the LLM is unavailable) ────────

def _fallback_summary(
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


# ─── Main entry point ─────────────────────────────────────────────────────────

async def analyze(txn: NormalizedTransaction, history: list[NormalizedTransaction]) -> FraudAnalysis:
    threshold = _ctr_threshold(txn.currency)

    profile = _compute_behavioral_profile(history, threshold)
    ctr = _assess_ctr(txn, history, threshold)
    risk = _compute_risk_score(txn, history, profile, threshold)

    # Reasons are generated deterministically — no hallucination risk
    reasons = _plain_reasons(txn, risk, profile, ctr, threshold)

    # Determine fraud verdict from risk level
    hard_fraud_signals = {"near_threshold_amount", "velocity_clustering",
                          "outward_smurfing", "multi_source_smurfing"}
    has_hard_signal = bool(hard_fraud_signals & risk.components.keys())

    if risk.level == "LOW" and not has_hard_signal:
        is_fraudulent = False
        confidence = "LOW"
    elif risk.level == "MEDIUM":
        is_fraudulent = True
        confidence = "MEDIUM"
    else:
        is_fraudulent = True
        confidence = "HIGH"

    fraud_type = _pick_fraud_type(risk) if is_fraudulent else None
    sar_recommended, sar_reason = _assess_sar(txn, risk, is_fraudulent, threshold)

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
            f"  Time    : {txn.timestamp.strftime('%H:%M') if isinstance(txn.timestamp, datetime) else 'unknown'}  {t_status}"
        )
    else:
        delta_block = (
            f"ACCOUNT BASELINE: No prior transaction history.\n\n"
            f"THIS TRANSACTION:\n"
            f"  Amount  : {txn.currency} {txn.amount:,.2f}\n"
            f"  To      : {txn.counterparty_name or txn.counterparty_account or 'unknown'}\n"
            f"  Channel : {txn.channel or 'unknown'}\n"
            f"  Time    : {txn.timestamp.strftime('%H:%M') if isinstance(txn.timestamp, datetime) else 'unknown'}"
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

    # The LLM only produces the human-readable prose. Everything that determines
    # whether a case is raised (risk score, CTR/SAR, reasons) is already computed
    # deterministically above, so an LLM outage must never block a case — we fall
    # back to a deterministic summary instead of letting the exception propagate.
    summary = ""
    try:
        response = await _get_client().chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": summary_prompt},
            ],
            max_tokens=200,
            temperature=0,
        )
        raw = (response.choices[0].message.content or "").strip()
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
        summary = _fallback_summary(txn, risk, profile, reasons, ctr)

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
    )


def _format_history(txns: list[NormalizedTransaction]) -> str:
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
