import re

from backend.adapters.base import NormalizedTransaction

# ─── Currency-aware CTR thresholds ────────────────────────────────────────────
# Cash-transaction reporting threshold. In the US this is the FinCEN / Bank
# Secrecy Act CTR threshold (USD 10,000, per 31 CFR 1010.311). Other rows are
# the local-currency equivalents for jurisdictions we've onboarded.
# Add currencies here as new bank configs are onboarded.
CTR_THRESHOLDS: dict[str, float] = {
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
BATCH_PATTERN = re.compile(
    r"\b(batch|payroll|pay[\s\-]?run|salary|salaries|wages|bulk|sweep|"
    r"standing[\s\-]?order|scheduled|auto[\s\-]?debit|direct[\s\-]?debit|"
    r"regular[\s\-]?payment|monthly[\s\-]?payment|quarterly|disbursement)\b",
    re.IGNORECASE,
)


def apply_rule_overrides(rules: dict) -> None:
    """Apply operator-tuned detection parameters (from bank_config 'rules').
    Called at import and live from the settings API. Unknown keys are ignored."""
    global SAR_RATIO, STRUCTURING_BAND_RATIO, ROLLING_WINDOW_DAYS, SMURFING_WINDOW_HOURS
    if not rules:
        return
    if isinstance(rules.get("ctr_thresholds"), dict):
        for cur, val in rules["ctr_thresholds"].items():
            try:
                CTR_THRESHOLDS[str(cur).upper()] = float(val)
            except (TypeError, ValueError):
                pass
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
        "ctr_thresholds": dict(CTR_THRESHOLDS),
        "sar_ratio": SAR_RATIO,
        "structuring_band_ratio": STRUCTURING_BAND_RATIO,
        "rolling_window_days": ROLLING_WINDOW_DAYS,
        "smurfing_window_hours": SMURFING_WINDOW_HOURS,
    }


def restore_rules(snap: dict) -> None:
    """Restore parameters captured by snapshot_rules() (backtest cleanup)."""
    global SAR_RATIO, STRUCTURING_BAND_RATIO, ROLLING_WINDOW_DAYS, SMURFING_WINDOW_HOURS
    CTR_THRESHOLDS.clear()
    CTR_THRESHOLDS.update(snap["ctr_thresholds"])
    SAR_RATIO = snap["sar_ratio"]
    STRUCTURING_BAND_RATIO = snap["structuring_band_ratio"]
    ROLLING_WINDOW_DAYS = snap["rolling_window_days"]
    SMURFING_WINDOW_HOURS = snap["smurfing_window_hours"]


def ctr_threshold(currency: str) -> float:
    return CTR_THRESHOLDS.get((currency or "USD").upper(), 10_000)


def sar_threshold(currency: str) -> float:
    return ctr_threshold(currency) * SAR_RATIO


def detect_batch(txn: NormalizedTransaction) -> str | None:
    """Return the batch identifier if the transaction looks like a systematic payment, else None."""
    if txn.batch_id:
        return txn.batch_id
    if txn.reference and BATCH_PATTERN.search(txn.reference):
        return txn.reference
    return None