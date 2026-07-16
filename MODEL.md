# Detection model methodology

This document describes every threshold and rule in the FMS risk engine, the rationale behind each, and how the design maps to US supervisory expectations for model risk management (interagency SR 26-2 (2026), which superseded FRB SR 11-7 / OCC 2011-12 and the 2021 interagency statement on model risk for BSA/AML systems) and the FFIEC BSA/AML Examination Manual's expectations for suspicious-activity monitoring systems. SR 26-2's risk-based, materiality-scaled oversight expectations favor exactly this kind of simple, fully documented deterministic engine.

> **Scope honesty:** FMS is an open-source project, not a validated production model. This document provides the *documentation* layer of model risk management — inventory, design rationale, and testing evidence. Independent validation, institution-specific tuning, and above/below-the-line testing on production data remain the deploying institution's responsibility.

## Design principles

1. **Deterministic and explainable.** Every score is a sum of named components; every component carries a human-readable reason with the actual numbers. There is no black-box scoring. This supports the examiner expectation that an institution can explain why any alert did or did not fire.
2. **The LLM never decides.** The optional LLM writes prose summaries only. Scores, CTR/SAR assessments, sanctions matches, and case creation are all deterministic and function identically with the LLM disabled or unavailable.
3. **Never-miss processing.** Poller checkpoints only advance after a case is durably committed; analysis failures retry rather than skip. A monitoring gap is treated as worse than a processing delay.

## Regulatory thresholds (fixed by rule, not tuned)

| Parameter | Value | Basis |
|---|---|---|
| CTR threshold (USD) | $10,000 | 31 CFR 1010.311 — currency transactions over $10,000 in one business day |
| CTR same-day aggregation | same direction, same calendar day | 31 CFR 1010.313 — multiple transactions aggregate toward the threshold |
| SAR threshold | $5,000 (CTR × 0.5) | 31 CFR 1020.320 — suspicious activity aggregating $5,000+ with an identifiable suspect |
| Structuring reportable at any amount | yes | 31 CFR 1010.314; structuring is itself the suspicious activity |
| SAR filing window | 30 calendar days from detection | 31 CFR 1020.320(b)(3) |
| Non-USD CTR equivalents | per-currency table in `analyzer.py` | Local-jurisdiction reporting equivalents; documented inline with FX rationale |

## Behavioral / detection parameters (tunable heuristics)

These are heuristic starting points chosen for a mid-sized retail/SME transaction profile. Deploying institutions should recalibrate against their own volumes (see *Tuning guidance*).

| Parameter | Value | Rationale |
|---|---|---|
| Structuring band | 90–100% of CTR threshold (`STRUCTURING_BAND_RATIO = 0.9`) | Classic structuring clusters just under the reporting line; a 10% band balances catch-rate against false positives on ordinary round-number payments |
| Rolling velocity window | 5 days (`ROLLING_WINDOW_DAYS`) | Long enough to catch multi-day splitting, short enough that unrelated activity doesn't aggregate |
| Smurfing window | 48 hours, ≥3 distinct senders, aggregate ≥ CTR threshold | Multi-source placement typically completes within 1–2 days; 3+ distinct sources distinguishes coordination from coincidence |
| Behavioral deviation | z-score bands: ≤1σ none, ≤2σ +10, ≤3σ +22, >3σ +35 | Standard-deviation banding against the account's own history; new accounts are scored separately since no baseline exists |
| Established high-value pattern discount | −10 when ≥3 prior CTR-level transactions and deviation not ANOMALOUS | An account that routinely moves large amounts should not alert on every large amount; the discount is withheld when the amount is anomalous even for that account |
| Batch/systematic payment discount | −20 on batch ID or payroll/batch reference match | Bulk payroll/supplier runs are the dominant false-positive source for amount-based rules |
| New counterparty | +6 (+12 if amount ≥ CTR threshold) | First payment to an unknown beneficiary is the strongest single invoice-fraud/BEC signal |
| Odd hours | +8 for 01:00–04:59 | Account-takeover activity skews to hours when the legitimate holder is unlikely to notice |
| New channel | +5 | Channel change is a secondary takeover indicator |
| Same-day velocity | +5 at ≥3 txns, +10 at ≥5 | Burst activity indicator, deliberately small to avoid punishing busy legitimate days |

## Risk level cut-offs

| Score | Level | Case outcome |
|---|---|---|
| 0–30 | LOW | CLEAN unless a hard signal (structuring/smurfing/velocity) is present |
| 31–55 | MEDIUM | Case opened, confidence MEDIUM |
| 56–75 | HIGH | Case opened, confidence HIGH |
| 76–100 | CRITICAL | Case opened, confidence HIGH |

Hard money-laundering signals (near-threshold amount, velocity clustering, outward/multi-source smurfing) always open a case regardless of total score, because structuring is reportable irrespective of amount.

## Sanctions screening

Counterparty names are screened against the OFAC SDN list (primary names + aliases; refresh via `scripts/update_ofac.py`). Matching is normalized exact + token-overlap + sequence similarity with a 0.90 default threshold — high enough to suppress single-shared-token false positives, low enough to catch case/punctuation/suffix and token-order variants. A hit **overrides** the behavioral score: the case is forced HIGH with an explicit block-or-reject instruction, reflecting that OFAC obligations are absolute rather than risk-weighted. Every match reports its score, matched entry, and sanctions program for human adjudication.

## Testing evidence

`tests/` contains the current validation evidence, runnable offline (`python -m pytest`):

- **Regulatory logic:** CTR single/aggregate/below-threshold; SAR at threshold, for structuring at any amount, and suppression for non-suspicious activity.
- **Detection:** structuring band, velocity clustering, multi-source smurfing, behavioral deviation, new-account handling, batch suppression (including that a batched large transfer scores below an identical unbatched one).
- **Sanctions:** exact/case/punctuation/token-order matching, corporate-suffix noise, false-positive controls (ordinary names and single-shared-token names must not match), and null-safety.

## Tuning guidance for deploying institutions

1. Run FMS in observation mode against ≥90 days of historical data.
2. Review flagged-case precision with your BSA officer; adjust the structuring band and z-score bands first — they dominate alert volume.
3. Document every change to this file's parameters, with before/after alert-volume evidence (this constitutes your above/below-the-line record).
4. Re-run the test suite after any change; add institution-specific tests for adjusted thresholds.
5. Refresh the OFAC list at least daily in production (`scripts/update_ofac.py` via a scheduled task).
