from datetime import datetime

from backend.adapters.base import NormalizedTransaction
from backend.services.profiler import BehavioralProfile
from backend.services.regulatory import CTRAssessment
from backend.services.risk_engine import RiskScoreResult


def pick_fraud_type(risk: RiskScoreResult) -> str | None:
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


def plain_reasons(
    txn: NormalizedTransaction,
    risk: RiskScoreResult,
    profile: BehavioralProfile,
    ctr: CTRAssessment,
    threshold: float,
) -> list[str]:
    """Generate plain-English reason templates (no AI needed — deterministic)."""
    c = risk.components
    cur = txn.currency
    receiving = txn.direction == "INWARD"
    moves = "receives" if receiving else "sends"
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
            f"This transfer of {cur} {txn.amount:,.2f} is significantly above the "
            f"{cur} {threshold:,.0f} high-value threshold."
        )

    if "near_threshold_amount" in c:
        reasons.append(
            f"The amount ({cur} {txn.amount:,.2f}) sits just below the {cur} {threshold:,.0f} "
            f"reporting threshold — a pattern of multiple such amounts could indicate deliberate splitting."
        )

    if "velocity_clustering" in c:
        verb = "received" if receiving else "made"
        reasons.append(
            f"This account {verb} {risk.rolling_5d_count} transfers over the past 5 days "
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
        name = txn.counterparty_name or txn.counterparty_account or ("the sender" if receiving else "the recipient")
        if receiving:
            reasons.append(f"{name} has never sent money to this account before.")
        else:
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