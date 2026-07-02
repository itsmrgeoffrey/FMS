"""Unit tests for the deterministic fraud-scoring engine.

These cover everything that decides whether a case is raised — risk scoring,
CTR/SAR assessment, batch suppression — without touching the network or the
LLM. Run from the project root:  python -m pytest
"""
from datetime import datetime, timedelta

from backend.adapters.base import NormalizedTransaction
from backend.services import analyzer as A

BASE = datetime(2026, 6, 1, 12, 0, 0)


def txn(**kw) -> NormalizedTransaction:
    defaults = dict(
        id="t1",
        account_id="acc-1",
        amount=1_000.0,
        direction="OUTWARD",
        timestamp=BASE,
        counterparty_account="cp-1",
        counterparty_name="Known Vendor",
        channel="online",
        currency="USD",
        reference=None,
        status="completed",
        source_table="outward",
        batch_id=None,
    )
    defaults.update(kw)
    return NormalizedTransaction(**defaults)


def history_of(amounts, *, cp="cp-1", direction="OUTWARD", channel="online", start=None):
    """Build a benign history: same counterparty, same channel, one txn/day back."""
    start = start or (BASE - timedelta(days=30))
    return [
        txn(id=f"h{i}", amount=a, counterparty_account=cp, direction=direction,
            channel=channel, timestamp=start + timedelta(days=i))
        for i, a in enumerate(amounts)
    ]


def analyze_score(t, hist):
    threshold = A._ctr_threshold(t.currency)
    profile = A._compute_behavioral_profile(hist, threshold)
    return A._compute_risk_score(t, hist, profile, threshold)


# ─── Thresholds ───────────────────────────────────────────────────────────────

def test_us_ctr_threshold_is_10k():
    assert A._ctr_threshold("USD") == 10_000


def test_sar_is_half_of_ctr():
    assert A._sar_threshold("USD") == 5_000


def test_unknown_currency_defaults_to_usd_threshold():
    assert A._ctr_threshold("XYZ") == 10_000
    assert A._ctr_threshold(None) == 10_000


# ─── CTR assessment ─────────────────────────────────────────────────────────

def test_ctr_single_transaction_over_threshold():
    t = txn(amount=12_000)
    ctr = A._assess_ctr(t, [], A._ctr_threshold("USD"))
    assert ctr.required and ctr.trigger == "SINGLE_TXN"


def test_ctr_same_day_aggregate():
    t = txn(amount=6_000, timestamp=BASE)
    same_day = [txn(id="a", amount=5_000, timestamp=BASE - timedelta(hours=2))]
    ctr = A._assess_ctr(t, same_day, A._ctr_threshold("USD"))
    assert ctr.required and ctr.trigger == "SAME_DAY_AGGREGATE"


def test_ctr_not_required_below_threshold():
    ctr = A._assess_ctr(txn(amount=2_000), [], A._ctr_threshold("USD"))
    assert not ctr.required


# ─── Risk scoring behaviour ─────────────────────────────────────────────────

def test_consistent_activity_scores_low():
    hist = history_of([1_000, 1_050, 950, 1_100, 900])
    risk = analyze_score(txn(amount=1_000), hist)
    assert risk.level == "LOW"


def test_near_threshold_amount_flags_structuring():
    # 9,500 sits in the structuring band (0.9 * 10k .. 10k-1)
    hist = history_of([1_000, 1_050, 950])
    risk = analyze_score(txn(amount=9_500), hist)
    assert "near_threshold_amount" in risk.components


def test_high_value_over_threshold_flagged():
    hist = history_of([1_000, 1_050, 950])
    risk = analyze_score(txn(amount=40_000), hist)
    assert "high_value_transfer" in risk.components
    assert risk.level != "LOW"  # a 40x-average transfer must not be treated as normal


def test_new_account_has_no_history_risk():
    risk = analyze_score(txn(amount=8_000), [])
    assert risk.behavioral_verdict == "NEW_ACCOUNT"
    assert "new_account_risk" in risk.components


def test_batch_reference_suppresses_score():
    hist = history_of([1_000, 1_050, 950])
    plain = analyze_score(txn(amount=40_000), hist)
    batched = analyze_score(txn(amount=40_000, reference="Monthly PAYROLL run"), hist)
    assert "batch_payment" in batched.components
    assert batched.score < plain.score


def test_multi_source_smurfing_detected():
    # 4 distinct senders in the last 48h totalling > threshold, all inward
    hist = [
        txn(id=f"in{i}", amount=3_000, direction="INWARD",
            counterparty_account=f"sender-{i}", timestamp=BASE - timedelta(hours=i + 1))
        for i in range(4)
    ]
    t = txn(amount=3_000, direction="INWARD", counterparty_account="sender-x")
    risk = analyze_score(t, hist)
    assert "multi_source_smurfing" in risk.components


def test_velocity_clustering_detected():
    # Several sub-threshold transfers over 5 days that together exceed threshold
    hist = history_of([4_000, 4_000, 4_000], start=BASE - timedelta(days=3))
    t = txn(amount=4_000, timestamp=BASE)
    risk = analyze_score(t, hist)
    assert "velocity_clustering" in risk.components


# ─── SAR assessment ─────────────────────────────────────────────────────────

def test_sar_not_recommended_when_not_fraudulent():
    hist = history_of([1_000, 1_050, 950])
    risk = analyze_score(txn(amount=1_000), hist)
    rec, reason = A._assess_sar(txn(amount=1_000), risk, is_fraudulent=False,
                                ctr_threshold=A._ctr_threshold("USD"))
    assert not rec and reason == ""


def test_sar_recommended_for_structuring_regardless_of_amount():
    hist = history_of([1_000, 1_050, 950])
    t = txn(amount=9_500)
    risk = analyze_score(t, hist)
    rec, reason = A._assess_sar(t, risk, is_fraudulent=True,
                                ctr_threshold=A._ctr_threshold("USD"))
    assert rec and "structuring" in reason.lower()


def test_sar_recommended_for_large_suspicious_amount():
    hist = history_of([1_000, 1_050, 950])
    t = txn(amount=40_000)
    risk = analyze_score(t, hist)
    rec, reason = A._assess_sar(t, risk, is_fraudulent=True,
                                ctr_threshold=A._ctr_threshold("USD"))
    assert rec and "SAR" in reason


# ─── Batch detection helper ─────────────────────────────────────────────────

def test_detect_batch_by_reference():
    assert A._detect_batch(txn(reference="salary disbursement")) is not None
    assert A._detect_batch(txn(reference="gift to friend")) is None


def test_detect_batch_by_batch_id():
    assert A._detect_batch(txn(batch_id="BATCH-99")) == "BATCH-99"
