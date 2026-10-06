# Detection model methodology

> Current implementation boundaries and operational checks: [Current Scope](docs/CURRENT_SCOPE.md). This is a review model, not a legal filing determination or independent validation.

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
| CTR same-day aggregation | same direction, cash only, source business date or configured timezone | Account-level review only; related-person aggregation and exemptions require verification |
| SAR assessment | suspicious USD activity at least $5,000 | US-bank officer review; not derived from tunable behavioral benchmarks |
| Structuring patterns below threshold | review alert | No blanket assertion that every pattern mandates a SAR at any amount |
| SAR date reminders | provisional, based on case creation | The legally relevant initial-detection date and filing lifecycle are not established by FMS |
| Non-USD reporting | manual assessment | Currency benchmarks in `analyzer.py` are behavioral heuristics, not local law |

## Behavioral / detection parameters (tunable heuristics)

These are heuristic starting points chosen for a mid-sized retail/SME transaction profile. Deploying institutions should recalibrate against their own volumes (see *Tuning guidance*).

| Parameter | Value | Rationale |
|---|---|---|
| Structuring band | 90–100% of CTR threshold (`STRUCTURING_BAND_RATIO = 0.9`) | Classic structuring clusters just under the reporting line; a 10% band balances catch-rate against false positives on ordinary round-number payments |
| Rolling velocity window | 5 days (`ROLLING_WINDOW_DAYS`) | Long enough to catch multi-day splitting, short enough that unrelated activity doesn't aggregate |
| Smurfing window | 48 hours, ≥3 distinct senders, aggregate ≥ CTR threshold | Multi-source placement typically completes within 1–2 days; 3+ distinct sources distinguishes coordination from coincidence |
| Behavioral deviation | z-score bands: ≤1σ none, ≤2σ +10, ≤3σ +22, >3σ +35 | Standard-deviation banding against the account's own history; new accounts are scored separately since no baseline exists |
| Established high-value pattern discount | −10 when ≥3 prior CTR-level transactions and deviation not ANOMALOUS | An account that routinely moves large amounts should not alert on every large amount; the discount is withheld when the amount is anomalous even for that account |
| Batch/systematic payment discount | disabled | Reference text and unverified batch IDs are not trusted provenance |
| New counterparty | +6 (+12 if amount ≥ CTR threshold) | First payment to an unknown beneficiary is the strongest single invoice-fraud/BEC signal |
| Odd hours | +8 for 01:00–04:59 | Account-takeover activity skews to hours when the legitimate holder is unlikely to notice |
| New channel | +5 | Channel change is a secondary takeover indicator |
| Same-day velocity | +5 at ≥3 txns, +10 at ≥5 | Burst activity indicator, deliberately small to avoid punishing busy legitimate days |

## Risk level cut-offs

| Score | Level | Case outcome |
|---|---|---|
| 0–30 | LOW | CLEAN only when there is no pattern, reporting, or screening review requirement |
| 31–55 | MEDIUM | Case opened, confidence MEDIUM |
| 56–75 | HIGH | Case opened, confidence HIGH |
| 76–100 | CRITICAL | Case opened, confidence HIGH |

Pattern signals (near-threshold amount, velocity clustering, outward/multi-source smurfing) open a review regardless of total score. A pattern is neither confirmed laundering nor an automatic legal reporting determination.

## Sanctions screening

Account-holder and counterparty names are screened through the shared analyzer. Matching is normalized exact, token-overlap, and sequence similarity with a 0.90 default threshold. A candidate opens a review without converting name similarity into confirmed identity or fraud. Evidence includes party, list, matched name, similarity, program, and list age. Missing names, unusable full lists, or stale lists require manual review.

## Testing evidence

`tests/` contains the current validation evidence, runnable offline (`python -m pytest`):

- **Regulatory logic:** strict cash CTR boundary, business-day aggregates, non-cash exclusion, manual scope checks, fixed SAR assessment, and separation from tunable benchmarks.
- **Detection:** structuring band, velocity, smurfing, deviation, same-currency historical isolation, and resistance to payroll-reference score suppression.
- **Processing and access:** concurrent submissions, idempotency conflicts, interrupted processing, durable delivery retries, review pagination, session revocation, and WebSocket authorization.
- **Sanctions:** exact/case/punctuation/token-order matching, corporate-suffix noise, false-positive controls (ordinary names and single-shared-token names must not match), and null-safety.

## Tuning guidance for deploying institutions

1. Run FMS in observation mode against ≥90 days of historical data.
2. Review flagged-case precision with your BSA officer; adjust the structuring band and z-score bands first — they dominate alert volume.
3. Document every change to this file's parameters, with before/after alert-volume evidence (this constitutes your above/below-the-line record).
4. Re-run the test suite after any change; add institution-specific tests for adjusted thresholds.
5. Refresh the OFAC list at least daily in production (`scripts/update_ofac.py` via a scheduled task).
