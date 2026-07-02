# Regulatory alignment

FMS is designed around US Bank Secrecy Act (BSA) reporting obligations administered by **FinCEN** (the Financial Crimes Enforcement Network, US Department of the Treasury). This document maps what the system detects to the underlying requirements.

> **Important:** FMS is a decision-support tool. It **flags** activity and **prepares** filing lists. It does **not** file reports with FinCEN, and it does **not** constitute legal or compliance advice. Every determination and filing remains the responsibility of the institution and its qualified BSA/AML officer. Thresholds, forms, and deadlines change — always verify against current FinCEN guidance and your BSA officer.

## Currency Transaction Report (CTR)

- **Rule:** A CTR is required for currency transactions exceeding **USD $10,000** in a business day, including multiple transactions that aggregate above the threshold (31 CFR 1010.311).
- **What FMS does:** `_assess_ctr()` flags (a) any single transaction at/above the currency-aware threshold and (b) same-direction, same-day aggregates that cross it. Thresholds are defined per currency in `backend/services/analyzer.py` (USD $10,000 and local-currency equivalents).
- **Where to see it:** the `ctr_required` flag and reason on each case, and the `/reports/ctr` export.

## Suspicious Activity Report (SAR)

- **Rule:** A bank must file a SAR for suspicious activity aggregating to **USD $5,000 or more** where a suspect can be identified (31 CFR 1020.320). Certain patterns — notably **structuring** — are reportable **regardless of amount** (31 CFR 1010.314).
- **What FMS does:** `_assess_sar()` recommends a SAR when a case is flagged and either (a) a structuring/smurfing signal is present (any amount) or (b) the suspicious amount meets the SAR threshold (half the CTR threshold).
- **Where to see it:** the `sar_recommended` flag and reason on each case, and the `/reports/sar` export.
- **Note on deadlines:** SARs generally must be filed within 30 calendar days of initial detection. FMS timestamps detection (case `created_at`) to support that clock, but does not track or enforce filing deadlines.

## CTR vs. SAR — a deliberate distinction

FMS keeps these two tracks separate, because they are separate obligations:

- A large, **routine** transaction (e.g. an established customer's regular six-figure wire to a known vendor) may require a **CTR** while being **not suspicious** — no SAR.
- A pattern of **small** deposits structured to stay under $10,000 may warrant a **SAR** for structuring even though **no single transaction** triggers a CTR.

The engine models both independently so a compliance officer sees the right obligation for the right reason.

## What FMS does *not* do

- It does not transmit anything to FinCEN or any regulator.
- It does not complete FinCEN Form 112 (CTR) or Form 111 (SAR).
- It does not make final suspicious/not-suspicious determinations — a human officer does.
- It does not track filing deadlines, exemptions (e.g. CTR exempt persons), or recordkeeping retention.

Use FMS to surface and organize; use your BSA/AML program to decide and file.
