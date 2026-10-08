import json
import logging
import re
import statistics
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
from groq import AsyncGroq
from backend.adapters.base import NormalizedTransaction
from backend.config import bank_config, settings
from backend.services import sanctions

log = logging.getLogger(__name__)

_client: AsyncGroq | None = None


def _get_client() -> AsyncGroq:
    """Construct the Groq client lazily so importing this module (e.g. in tests)
    doesn't require an API key — only generating a summary does."""
    global _client
    if _client is None:
        _client = AsyncGroq(api_key=settings.groq_api_key, timeout=30, max_retries=1)
    return _client


async def _generate_summary_text(system: str, user: str) -> str:
    """Call the configured LLM. If LLM_BASE_URL is set, use that OpenAI-compatible
    endpoint (e.g. a local Ollama) so transaction data never leaves the host;
    otherwise fall back to Groq. Raises on failure — the caller handles fallback."""
    if settings.llm_base_url:
        import httpx
        headers = {"Content-Type": "application/json"}
        if settings.llm_api_key:
            headers["Authorization"] = f"Bearer {settings.llm_api_key}"
        async with httpx.AsyncClient(timeout=60) as http:
            resp = await http.post(
                settings.llm_base_url.rstrip("/") + "/chat/completions",
                headers=headers,
                json={
                    "model": settings.llm_model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "max_tokens": 200,
                    "temperature": 0,
                },
            )
            resp.raise_for_status()
            return (resp.json()["choices"][0]["message"]["content"] or "").strip()

    response = await _get_client().chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=200,
        temperature=0,
    )
    return (response.choices[0].message.content or "").strip()

# ─── Currency-aware CTR thresholds ────────────────────────────────────────────
# Behavioral high-value benchmarks, NOT statutory reporting thresholds.
# Legacy configuration uses the name ctr_thresholds for these values.
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

# Legacy configuration compatibility only; reporting does not use this ratio.
SAR_RATIO = 0.5

ROLLING_WINDOW_DAYS = 5
SMURFING_WINDOW_HOURS = 48
STRUCTURING_BAND_RATIO = 0.9   # bottom of near-threshold band = 90% of high-value threshold

def validate_rule_overrides(rules: dict) -> dict:
    if not isinstance(rules, dict):
        raise ValueError("Rules must be an object")
    unknown = set(rules) - {"ctr_thresholds", "sar_ratio", "structuring_band_ratio",
                            "rolling_window_days", "smurfing_window_hours"}
    if unknown:
        raise ValueError("Unsupported rule settings: " + ", ".join(sorted(unknown)))
    values = dict(rules)
    if "ctr_thresholds" in values:
        if not isinstance(values["ctr_thresholds"], dict):
            raise ValueError("Behavioral benchmarks must be a currency-to-amount mapping")
        thresholds = {}
        for currency, raw in values["ctr_thresholds"].items():
            if isinstance(raw, bool):
                raise ValueError("Behavioral benchmarks must be numeric amounts, not booleans")
            currency = str(currency).upper()
            number = float(raw)
            if not re.fullmatch(r"[A-Z]{3}", currency) or not math.isfinite(number) or number <= 0:
                raise ValueError("Behavioral benchmarks require a currency code and positive finite amount")
            thresholds[currency] = number
        values["ctr_thresholds"] = thresholds
    for key, maximum in (("rolling_window_days", 365), ("smurfing_window_hours", 8760)):
        if key in values:
            if isinstance(values[key], bool):
                raise ValueError(f"{key} must be a number, not a boolean")
            number = float(values[key])
            if not math.isfinite(number) or not number.is_integer() or not 1 <= number <= maximum:
                raise ValueError(f"{key} must be a whole number between 1 and {maximum}")
            values[key] = int(number)
    for key in ("structuring_band_ratio", "sar_ratio"):
        if key in values:
            number = float(values[key])
            if not math.isfinite(number) or not 0 < number < 1:
                raise ValueError(f"{key} must be between 0 and 1, exclusive")
            values[key] = number
    return values


def apply_rule_overrides(rules: dict) -> None:
    """Apply operator-tuned detection parameters (from bank_config 'rules').
    Called at import and live from the settings API. Unknown keys are rejected."""
    global SAR_RATIO, STRUCTURING_BAND_RATIO, ROLLING_WINDOW_DAYS, SMURFING_WINDOW_HOURS
    if not rules:
        return
    rules = validate_rule_overrides(rules)
    if isinstance(rules.get("ctr_thresholds"), dict):
        for cur, val in rules["ctr_thresholds"].items():
            try:
                number = float(val)
                if not math.isfinite(number) or number <= 0:
                    raise ValueError("Behavioral benchmarks must be positive and finite")
                _CTR_THRESHOLDS[str(cur).upper()] = number
            except (TypeError, ValueError):
                raise ValueError("Behavioral benchmarks must be positive and finite")
    for key, cast in (("sar_ratio", float), ("structuring_band_ratio", float),
                      ("rolling_window_days", int), ("smurfing_window_hours", int)):
        if rules.get(key) is not None:
            try:
                value = cast(rules[key])
            except (TypeError, ValueError):
                continue
            if key == "sar_ratio":
                SAR_RATIO = value
            elif key == "structuring_band_ratio":
                STRUCTURING_BAND_RATIO = value
            elif key == "rolling_window_days":
                ROLLING_WINDOW_DAYS = value
            elif key == "smurfing_window_hours":
                SMURFING_WINDOW_HOURS = value


def snapshot_rules() -> dict:
    """Current tunable parameters, in the same shape apply_rule_overrides()
    accepts — used for the tuning log and to save/restore around backtests."""
    return {
        "ctr_thresholds": dict(_CTR_THRESHOLDS),
        "sar_ratio": SAR_RATIO,
        "structuring_band_ratio": STRUCTURING_BAND_RATIO,
        "rolling_window_days": ROLLING_WINDOW_DAYS,
        "smurfing_window_hours": SMURFING_WINDOW_HOURS,
    }


def restore_rules(snap: dict) -> None:
    """Restore parameters captured by snapshot_rules() (backtest cleanup)."""
    global SAR_RATIO, STRUCTURING_BAND_RATIO, ROLLING_WINDOW_DAYS, SMURFING_WINDOW_HOURS
    _CTR_THRESHOLDS.clear()
    _CTR_THRESHOLDS.update(snap["ctr_thresholds"])
    SAR_RATIO = snap["sar_ratio"]
    STRUCTURING_BAND_RATIO = snap["structuring_band_ratio"]
    ROLLING_WINDOW_DAYS = snap["rolling_window_days"]
    SMURFING_WINDOW_HOURS = snap["smurfing_window_hours"]


def _ctr_threshold(currency: str) -> float:
    return _CTR_THRESHOLDS.get((currency or "").upper(), float("inf"))


def _sar_threshold(currency: str) -> float:
    return _ctr_threshold(currency) * SAR_RATIO


def _detect_batch(txn: NormalizedTransaction) -> str | None:
    """No score discount without independently verified batch provenance."""
    return None


SYSTEM_PROMPT = (
    "You write plain-English fraud alert summaries for bank compliance officers. "
    "2–3 sentences only. No jargon, no scores, no internal system names. "
    "Focus on behaviour: what this account normally does, what this transaction does differently, "
    "and what the officer should do next. "
    "CTR and SAR flags require officer verification of filing applicability; they are not findings of fraud. "
    "Name matches are possible matches, never confirmed identity matches. "
    "Respond with valid JSON only. No markdown."
)


def _pick_fraud_type(risk: "RiskScoreResult") -> str | None:
    c = risk.components
    if "cross_branch_structuring" in c:
        return "cross-branch cash structuring"
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
    sanctions_hit: bool = False
    sanctions_detail: str = ""
    screening_status: str = "NOT_SCREENED"
    screening_matches: list | None = None
    regulatory_review: bool = False
    structuring_alert: bool = False
    assessed_rules: dict | None = None


def initial_case_status(is_fraudulent: bool, ctr_required: bool, sar_recommended: bool,
                        regulatory_review: bool = False) -> str:
    """Workflow status for a newly analyzed transaction.

    CTR is not fraud evidence, but it is still an officer action item. Keeping
    CTR-only transactions open prevents them from being hidden as clean activity.
    """
    return "OPEN" if is_fraudulent or ctr_required or sar_recommended or regulatory_review else "CLEAN"


def eligible_history(txn, history):
    cutoff = txn.timestamp - timedelta(days=int(bank_config.get("monitoring", {}).get("history_days", 90)))
    return [h for h in history if h.account_id == txn.account_id
            and h.currency == txn.currency and cutoff <= h.timestamp <= txn.timestamp
            and (h.source_table, h.id) != (txn.source_table, txn.id)]


def business_day(txn):
    return txn.business_date or txn.timestamp.replace(tzinfo=timezone.utc).astimezone(
        ZoneInfo(settings.business_timezone)).date().isoformat()


def supported_reporting(txn):
    return (settings.regulatory_jurisdiction.upper() == "US"
            and settings.institution_type.lower() == "bank" and txn.currency == "USD")


# ─── CTR obligation assessment ────────────────────────────────────────────────

def _assess_ctr(
    txn: NormalizedTransaction,
    history: list[NormalizedTransaction],
    threshold: float,
) -> CTRAssessment:
    if not supported_reporting(txn):
        return CTRAssessment(False, "Manual reporting assessment required: only US-bank USD rules are supported; no FX conversion or foreign reporting rule is inferred.", "MANUAL_REVIEW")
    if txn.is_cash is False:
        return CTRAssessment(False, "Non-cash transaction: outside the cash CTR assessment.", "NONE")
    if txn.is_cash is None:
        return CTRAssessment(False, "Cash classification missing: verify reporting applicability manually.", "MANUAL_REVIEW")
    threshold = Decimal("10000")
    if txn.amount > threshold:
        return CTRAssessment(
            required=True,
            reason=f"Cash transaction of USD {txn.amount:,.2f} exceeds $10,000. Verify exemptions and related-person aggregation before filing.",
            trigger="SINGLE_TXN",
        )

    today = business_day(txn)
    if today:
        same_day = [
            h for h in eligible_history(txn, history)
            if h.is_cash is True and business_day(h) == today
            and h.direction == txn.direction
        ]
        day_total = sum((h.amount for h in same_day), Decimal(0)) + txn.amount
        if day_total > threshold:
            return CTRAssessment(
                required=True,
                reason=(
                    f"Same-direction cash business-day aggregate: USD {day_total:,.2f} "
                    f"across {len(same_day) + 1} transactions. Verify exemptions and related-person aggregation before filing."
                ),
                trigger="SAME_DAY_AGGREGATE",
            )

    return CTRAssessment(required=False, reason="", trigger="NONE")


# ─── SAR obligation assessment ────────────────────────────────────────────────
# Pattern signals warrant review; they are not an automatic filing determination.
_STRUCTURING_SIGNALS = frozenset(
    {"near_threshold_amount", "near_miss_spike", "velocity_clustering",
     "outward_smurfing", "multi_source_smurfing", "cross_branch_structuring"}
)


def _assess_sar(
    txn: NormalizedTransaction,
    risk: "RiskScoreResult",
    is_fraudulent: bool,
    ctr_threshold: float,
) -> tuple[bool, str]:
    """Surface suspicious US-bank USD activity for an officer's SAR assessment."""
    if not is_fraudulent or not supported_reporting(txn):
        return False, ""

    cur = txn.currency
    sar_threshold = Decimal("5000")
    # Largest suspicious amount in play: the transaction itself or a suspicious aggregate.
    involved = max(
        txn.amount,
        risk.rolling_5d_total if risk.rolling_5d_count > 1 else 0.0,
        risk.inbound_total_48h,
    )
    if involved >= sar_threshold:
        return True, (
            f"Suspicious activity involving {cur} {involved:,.2f} meets the "
            f"{cur} {sar_threshold:,.0f} US-bank SAR assessment threshold. "
            "Officer review must establish suspicion and filing applicability; this is not a filing determination."
        )
    return False, ""


# ─── Rolling window helpers ───────────────────────────────────────────────────

def _rolling_window(
    txn: NormalizedTransaction,
    history: list[NormalizedTransaction],
    days: int | None = None,
) -> tuple[float, int]:
    """Total same-direction amount for this account in the last N days (including current txn)."""
    days = days if days is not None else ROLLING_WINDOW_DAYS  # read live (UI-tunable)
    if not isinstance(txn.timestamp, datetime):
        return txn.amount, 1
    history = eligible_history(txn, history)
    cutoff = txn.timestamp - timedelta(days=days)
    window = [
        h for h in history
        if isinstance(h.timestamp, datetime)
        and h.timestamp >= cutoff
        and h.direction == txn.direction
    ]
    return sum((h.amount for h in window), Decimal(0)) + txn.amount, len(window) + 1


def _inbound_sources(
    txn: NormalizedTransaction,
    history: list[NormalizedTransaction],
    hours: int | None = None,
) -> tuple[int, float]:
    """For INWARD txns: (distinct senders, total received) in the last N hours."""
    hours = hours if hours is not None else SMURFING_WINDOW_HOURS  # read live (UI-tunable)
    if txn.direction != "INWARD" or not isinstance(txn.timestamp, datetime):
        return 0, 0.0
    history = eligible_history(txn, history)
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
    total = sum((h.amount for h in recent), Decimal(0)) + txn.amount
    return len(senders), total


# ─── Behavioral profile ───────────────────────────────────────────────────────

def _compute_behavioral_profile(
    history: list[NormalizedTransaction],
    threshold: float,
    as_of: datetime | None = None,
) -> BehavioralProfile:
    if not history:
        return BehavioralProfile(
            transaction_count=0, avg_amount=0.0, max_amount=0.0, std_dev=0.0,
            ctr_level_count=0, large_txn_pct=0.0, known_counterparties=0,
            active_channels=[], days_active=0, recent_7d_count=0,
        )
    amounts = [float(h.amount) for h in history]
    avg = statistics.mean(amounts)
    std = statistics.stdev(amounts) if len(amounts) > 1 else 0.0
    cutoff = (as_of or datetime.utcnow()) - timedelta(days=7)
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
    history = eligible_history(txn, history)
    score = 0
    components: dict = {}
    behavioral_verdict = "CONSISTENT"

    structuring_low = threshold * STRUCTURING_BAND_RATIO
    structuring_high = threshold

    rolling_total, rolling_count = _rolling_window(txn, history)
    src_count_48h, inbound_total_48h = _inbound_sources(txn, history)

    # Cash split across branches/locations on one business day is a separate
    # suspicious pattern from CTR applicability. Every contributing item must
    # be individually at or below the benchmark; the aggregate may still
    # trigger CTR review independently under the reporting rules above.
    current_location = txn.branch_id or txn.location_id
    if txn.is_cash is True and current_location:
        today = business_day(txn)
        benchmark = Decimal(str(threshold))
        prior_cash = [
            h for h in history
            if h.is_cash is True
            and h.direction == txn.direction
            and business_day(h) == today
            and (h.branch_id or h.location_id)
            and h.amount <= benchmark
        ]
        cash_items = prior_cash + [txn]
        locations = {h.branch_id or h.location_id for h in cash_items}
        cash_total = sum((h.amount for h in cash_items), Decimal(0))
        if txn.amount <= benchmark and len(cash_items) >= 2 and len(locations) >= 2 and cash_total >= benchmark:
            components["cross_branch_structuring"] = {
                "score": 35,
                "transaction_count": len(cash_items),
                "location_count": len(locations),
                "aggregate": float(cash_total),
                "reason": (
                    f"{len(cash_items)} individually sub-threshold cash transactions across "
                    f"{len(locations)} branches or locations on {today} total "
                    f"{txn.currency} {cash_total:,.2f}"
                ),
            }
            score += 35

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
            (float(txn.amount) - profile.avg_amount) / profile.std_dev
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
        excess = float(txn.amount) - threshold
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
                f"Transfer of {txn.currency} {txn.amount:,.2f} meets or exceeds "
                f"the {txn.currency} {threshold:,.0f} behavioral high-value benchmark"
            ),
        }
        score += hv_pts

    # ── 3. Near-threshold amount (20) ────────────────────────────────────────
    if structuring_low <= txn.amount < structuring_high:
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
                f"with the current transaction below the behavioral benchmark"
            ),
        }
        score += 25

    # ── 5. Outward same-counterparty day accumulation / classic smurfing (20) ─
    today = business_day(txn)
    known_cps = {h.counterparty_account for h in history if h.counterparty_account}
    is_new_cp = txn.counterparty_account not in known_cps

    if today and txn.counterparty_account and txn.direction == "OUTWARD":
        cp_today = [
            h for h in history
            if h.counterparty_account == txn.counterparty_account
            and isinstance(h.timestamp, datetime)
            and business_day(h) == today
            and h.direction == "OUTWARD"
        ]
        cp_day_total = sum(h.amount for h in cp_today) + txn.amount
        if cp_day_total >= threshold and cp_today:
            components["outward_smurfing"] = {
                "score": 20,
                "reason": (
                    f"Cumulative outward to same beneficiary today: "
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
    if not (structuring_low <= txn.amount < structuring_high):
        cutoff5 = txn.timestamp - timedelta(days=ROLLING_WINDOW_DAYS) if isinstance(txn.timestamp, datetime) else None
        if cutoff5:
            near_miss_in_window = [
                h for h in history
                if structuring_low <= h.amount < structuring_high
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
            "reason": "Beneficiary or sender has never appeared in this account's transaction history",
        }
        score += cp_pts

    # ── 9. Odd hours (8) ──────────────────────────────────────────────────────
    hour = txn.timestamp.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(settings.business_timezone)).hour
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
        todays = [h for h in history if business_day(h) == today]
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
    receiving = txn.direction == "INWARD"
    moves = "receives" if receiving else "sends"
    reasons = []

    if "new_account_risk" in c:
        reasons.append(
            "This account has no previous transaction history — "
            "this is first-time activity on a new or unseasoned account."
        )

    # When the amount both deviates from the norm AND the account has an established
    # high-value pattern, the two facts read as contradictory if stated separately
    # ("far outside normal" vs. "consistent with their profile"). Merge them into a
    # single, coherent assessment so a reviewer isn't given mixed messaging.
    if "behavioral_deviation" in c and "established_high_value_pattern" in c:
        reasons.append(
            f"At {cur} {txn.amount:,.2f}, this is larger than this account's typical "
            f"{cur} {profile.avg_amount:,.0f} transaction — but the account has "
            f"{profile.ctr_level_count} prior high-value transactions, so the amount alone is only "
            f"moderately unusual for this profile."
        )
    elif "behavioral_deviation" in c:
        reasons.append(
            f"This transfer of {cur} {txn.amount:,.2f} is far outside what this account "
            f"normally {moves} — their typical transaction is around {cur} {profile.avg_amount:,.0f}."
        )
    elif "established_high_value_pattern" in c:
        reasons.append(
            f"This account regularly handles large amounts — it has {profile.ctr_level_count} "
            f"prior high-value transactions, so large amounts are consistent with its profile."
        )

    if "high_value_transfer" in c:
        reasons.append(
            f"This transfer of {cur} {txn.amount:,.2f} meets or exceeds the "
            f"{cur} {threshold:,.0f} behavioral high-value benchmark."
        )

    if "near_threshold_amount" in c:
        reasons.append(
            f"The amount ({cur} {txn.amount:,.2f}) sits just below the {cur} {threshold:,.0f} "
            f"reporting threshold — a pattern of multiple such amounts could indicate deliberate splitting."
        )

    if "cross_branch_structuring" in c:
        signal = c["cross_branch_structuring"]
        reasons.append(
            f"Structuring alert: {signal['transaction_count']} cash transactions across "
            f"{signal['location_count']} branches or locations on the same business day total "
            f"{cur} {signal['aggregate']:,.2f}; each transaction was at or below the "
            f"{cur} {threshold:,.0f} benchmark. Review for deliberate transaction splitting."
        )

    if "velocity_clustering" in c:
        verb = "received" if receiving else "made"
        reasons.append(
            f"This account {verb} {risk.rolling_5d_count} transfers over the past {ROLLING_WINDOW_DAYS} days "
            f"totalling {cur} {risk.rolling_5d_total:,.2f}, above the "
            f"{cur} {threshold:,.0f} behavioral benchmark, while the current transfer is below it."
        )

    if "outward_smurfing" in c:
        reasons.append(
            f"Multiple payments were sent to the same recipient today, "
            f"adding up to at least the {cur} {threshold:,.0f} behavioral benchmark."
        )

    if "multi_source_smurfing" in c:
        reasons.append(
            f"{risk.inbound_sources_48h} different accounts have deposited money into this account "
            f"in the last {SMURFING_WINDOW_HOURS} hours, totalling {cur} {risk.inbound_total_48h:,.2f} — "
            f"this pattern of multiple small deposits from different senders is known as smurfing."
        )

    if "near_miss_spike" in c:
        reasons.append(
            f"Several recent transactions from this account clustered just below the "
            f"{cur} {threshold:,.0f} threshold — an unusual pattern worth reviewing."
        )

    if "new_counterparty" in c:
        name = txn.counterparty_name or txn.counterparty_account or ("the sender" if receiving else "the beneficiary")
        if receiving:
            reasons.append(f"{name} has never sent money to this account before.")
        else:
            reasons.append(f"{name} has never received a payment from this account before.")

    if "odd_hours" in c:
        hour = txn.timestamp.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(settings.business_timezone)).hour
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
            f"this {cur} {txn.amount:,.2f} {txn.direction.lower()} transaction was assessed. "
        )
    else:
        opener = f"This {cur} {txn.amount:,.2f} {txn.direction.lower()} transaction was assessed with no prior account history. "
    body = " ".join(reasons[:2])
    action = ""
    if ctr.required:
        action += " A compliance officer must verify CTR filing applicability separately from the fraud assessment."
    return (opener + body + action).strip()


# ─── Deterministic verdict core ──────────────────────────────────────────────
# The complete rules-only evaluation (no sanctions screening, no LLM). analyze()
# builds on this, and rule backtesting replays it over stored history — one code
# path, so a backtest result is exactly what the live engine would have done.

_HARD_FRAUD_SIGNALS = frozenset(
    {"near_threshold_amount", "velocity_clustering", "outward_smurfing",
     "multi_source_smurfing", "cross_branch_structuring"}
)


def evaluate(txn: NormalizedTransaction, history: list[NormalizedTransaction]) -> dict:
    history = eligible_history(txn, history)
    threshold = _ctr_threshold(txn.currency)
    profile = _compute_behavioral_profile(history, threshold, txn.timestamp)
    ctr = _assess_ctr(txn, history, threshold)
    risk = _compute_risk_score(txn, history, profile, threshold)

    has_hard_signal = bool(_HARD_FRAUD_SIGNALS & risk.components.keys())
    if risk.level == "LOW" and not has_hard_signal:
        is_fraudulent, confidence = False, "LOW"
    elif risk.level == "MEDIUM":
        is_fraudulent, confidence = True, "MEDIUM"
    else:
        is_fraudulent, confidence = True, "HIGH"

    sar_recommended, sar_reason = _assess_sar(txn, risk, is_fraudulent, threshold)
    return {
        "threshold": threshold, "profile": profile, "ctr": ctr, "risk": risk,
        "is_fraudulent": is_fraudulent, "confidence": confidence,
        "sar_recommended": sar_recommended, "sar_reason": sar_reason,
    }


# ─── Main entry point ─────────────────────────────────────────────────────────

async def analyze(txn: NormalizedTransaction, history: list[NormalizedTransaction]) -> FraudAnalysis:
    from backend.services.installation import profile as operating_profile
    assessed_rules = {**snapshot_rules(), "operating_profile": operating_profile()}
    verdict = evaluate(txn, history)
    threshold, profile, ctr, risk = verdict["threshold"], verdict["profile"], verdict["ctr"], verdict["risk"]
    is_fraudulent, confidence = verdict["is_fraudulent"], verdict["confidence"]
    sar_recommended, sar_reason = verdict["sar_recommended"], verdict["sar_reason"]

    # Reasons are generated deterministically — no hallucination risk
    reasons = _plain_reasons(txn, risk, profile, ctr, threshold)

    fraud_type = _pick_fraud_type(risk) if is_fraudulent else None

    matches = []
    screening_status = "NO_MATCH"
    screening_notes = []
    party_role = "beneficiary" if txn.direction == "OUTWARD" else "sender"
    for role, name in (("account holder", txn.account_holder_name), (party_role, txn.counterparty_name)):
        if not name or not name.strip():
            screening_status = "INCOMPLETE" if screening_status == "NO_MATCH" else screening_status
            screening_notes.append(f"Manual screening required: {role} name is missing.")
            continue
        try:
            match = sanctions.screen(name)
        except sanctions.ScreeningUnavailable:
            screening_status = "UNAVAILABLE"
            screening_notes.append(f"Manual screening required: the list was unavailable for the {role}.")
            continue
        if match:
            matches.append({"party": role, "query": name, "matched_name": match.matched_name,
                            "source": match.source, "list_type": match.list_type,
                            "program": match.program, "score": match.score,
                            "list_age_hours": sanctions.list_age_hours()})
            screening_notes.append(
                f"Possible {match.list_type} name match: {role} '{name}' / '{match.matched_name}' "
                f"on {match.source} ({match.score:.0%} similarity). Verify identity and applicable "
                "restrictions with a compliance officer; name similarity is not a confirmed identity match."
            )
    if matches and screening_status != "UNAVAILABLE":
        screening_status = "POSSIBLE_MATCH"
    health = sanctions.status()
    if not health.get("ok"):
        screening_status = "UNAVAILABLE"
        screening_notes.append("Manual screening required: a usable full sanctions list is not available.")
    elif health.get("list_age_hours") is None or health["list_age_hours"] > max(24, settings.ofac_refresh_hours * 2):
        screening_status = "STALE"
        screening_notes.append("Manual screening required: sanctions-list freshness cannot be confirmed.")
    sanctions_hit = any(m["list_type"] == "SDN" for m in matches)
    sanctions_detail = " ".join(screening_notes)
    regulatory_review = ctr.trigger == "MANUAL_REVIEW"
    reasons = screening_notes + ([ctr.reason] if regulatory_review else []) + reasons

    reasons_text = "\n".join(f"- {r}" for r in reasons)

    # Structured delta report — gives the AI the specific numbers so its explanation
    # references actual values, not generic phrases.
    if profile.transaction_count > 0:
        amount_multiple = float(txn.amount) / profile.avg_amount if profile.avg_amount > 0 else 0
        cp_status = "(NEW — never seen before)" if "new_counterparty" in risk.components else f"(known {party_role})"
        ch_status = "(NEW — never used before)" if "new_channel" in risk.components else ""
        t_status = "(unusual hours — 01:00–04:00)" if "odd_hours" in risk.components else ""
        delta_block = (
            f"ACCOUNT BASELINE (last 90 days, {profile.transaction_count} transactions):\n"
            f"  Typical amount    : {txn.currency} {profile.avg_amount:,.0f}\n"
            f"  Historical max    : {txn.currency} {profile.max_amount:,.0f}\n"
            f"  Known beneficiaries/senders : {profile.known_counterparties}\n\n"
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
        f"\nREGULATORY NOTE: {ctr.reason} - CTR applicability requires officer verification, separate from fraud."
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
            raw = await _generate_summary_text(SYSTEM_PROMPT, summary_prompt)
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
        sanctions_hit=sanctions_hit,
        sanctions_detail=sanctions_detail,
        screening_status=screening_status,
        screening_matches=matches,
        regulatory_review=regulatory_review,
        structuring_alert="cross_branch_structuring" in risk.components,
        assessed_rules=assessed_rules,
    )


def _format_history(txns: list[NormalizedTransaction]) -> str:
    if not txns:
        return "No prior transactions found."
    lines = ["Timestamp              | Dir     | Amount        | Beneficiary / sender   | Channel"]
    lines.append("-" * 90)
    for t in txns[:50]:
        lines.append(
            f"{str(t.timestamp)[:19]:<22}| {t.direction:<8}| "
            f"{t.currency} {t.amount:>12,.2f} | {(t.counterparty_name or 'Unknown'):<22} | {t.channel or '-'}"
        )
    return "\n".join(lines)


# Apply operator-tuned rule overrides persisted in bank_config.yaml.
apply_rule_overrides(bank_config.get("rules", {}) or {})
