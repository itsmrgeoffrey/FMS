from dataclasses import dataclass
from datetime import datetime, timedelta

from backend.adapters.base import NormalizedTransaction
from backend.services.profiler import BehavioralProfile
from backend.services.rules_config import (
    ROLLING_WINDOW_DAYS, SMURFING_WINDOW_HOURS, STRUCTURING_BAND_RATIO,
    detect_batch,
)


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


def rolling_window(
    txn: NormalizedTransaction,
    history: list[NormalizedTransaction],
    days: int | None = None,
) -> tuple[float, int]:
    """Total same-direction amount for this account in the last N days (including current txn)."""
    days = days if days is not None else ROLLING_WINDOW_DAYS  # read live (UI-tunable)
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


def inbound_sources(
    txn: NormalizedTransaction,
    history: list[NormalizedTransaction],
    hours: int | None = None,
) -> tuple[int, float]:
    """For INWARD txns: (distinct senders, total received) in the last N hours."""
    hours = hours if hours is not None else SMURFING_WINDOW_HOURS  # read live (UI-tunable)
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


def compute_risk_score(
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

    rolling_total, rolling_count = rolling_window(txn, history)
    src_count_48h, inbound_total_48h = inbound_sources(txn, history)

    # ── 0. Batch / systematic payment signal (-20) ────────────────────────────
    # Check for a batch ID or reference pattern BEFORE applying behavioural checks.
    # A payroll run or supplier batch should not score the same as a one-off transfer
    # to an unknown counterparty just because the amount is large.
    batch_ref = detect_batch(txn)
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
                    f"This amount is much larger than this account's normal activity "
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