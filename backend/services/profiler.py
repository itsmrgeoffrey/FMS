import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta

from backend.adapters.base import NormalizedTransaction


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


def compute_behavioral_profile(
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