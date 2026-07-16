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
- **Note on deadlines:** SARs generally must be filed within 30 calendar days of initial detection (31 CFR 1020.320(b)(3)). FMS timestamps detection (case `created_at`) and reports the filing deadline and days remaining on every SAR report row. It tracks the clock; it does not enforce it.

## OFAC sanctions screening

- **Rule:** US persons are generally prohibited from transacting with parties on OFAC's Specially Designated Nationals (SDN) list; such transactions must be **blocked or rejected** and reported to OFAC (31 CFR Part 501). This obligation is absolute — it does not depend on suspicion or amount.
- **What FMS does:** every counterparty name is screened against the SDN list (primary names + aliases; refresh with `scripts/update_ofac.py`). A match overrides the risk score: the case is forced HIGH with an explicit block-or-reject instruction and the matched entry, program, and match score for human adjudication. Name screening produces false positives — verify before acting.
- **OFAC Consolidated (non-SDN) lists:** `scripts/update_ofac.py` also fetches the Consolidated lists (e.g. Sectoral Sanctions) into `data/ofac_consolidated.json`. A match raises a **review-required** case — these lists carry program-specific restrictions, not a blanket block obligation — with the program named for the officer.
- **Institution-supplied lists (UN/EU/UK or internal):** drop JSON files into `data/extra_lists/` using the same shape as the OFAC files (`[{"name", "program", "type", "source", "list_type"}]`; `list_type` defaults to `OTHER` = review-required, or set `SDN`/`PEP` per entry to control treatment). FMS does not bundle non-US lists.
- **PEP screening:** if a `data/pep.json` list is provided, matches are flagged for enhanced due diligence (not blocking). FMS does not bundle PEP data; quality PEP lists are typically commercial.
- **The 50% ownership rule is out of scope:** OFAC's guidance extends sanctions to entities 50%-or-more owned by listed parties. That determination requires beneficial-ownership data FMS does not hold — screening is name-based. Institutions with ownership data can express it as alias entries in an extra list.
- **Where to see it:** the red OFAC banner on a case (SDN), the review-required reason on watch-list cases, the `sanctions_hit`/`sanctions_detail` fields, and alert emails.

## SAR filing deadline

FMS timestamps detection (case `created_at`) and reports the 30-day filing deadline and days remaining on every SAR report row (31 CFR 1020.320(b)(3)). It tracks the clock; it does not enforce it.

## CTR vs. SAR — a deliberate distinction

FMS keeps these two tracks separate, because they are separate obligations:

- A large, **routine** transaction (e.g. an established customer's regular six-figure wire to a known vendor) may require a **CTR** while being **not suspicious** — no SAR.
- A pattern of **small** deposits structured to stay under $10,000 may warrant a **SAR** for structuring even though **no single transaction** triggers a CTR.

The engine models both independently so a compliance officer sees the right obligation for the right reason.

## Record retention

The BSA requires institutions to retain SAR/CTR filings and supporting documentation for **five years** (31 CFR 1010.430, 1020.320(d)). FMS **retains all cases, case actions, and audit-log entries indefinitely and never deletes them automatically.**

Optional, explicit retention enforcement exists for **raw ingested transaction rows only** (`FMS_RETENTION_DAYS`, **off by default**): when enabled, a daily job purges ingested-transaction rows older than the configured age and records the purge in the audit log. Cases, case actions, and the audit log itself are **never** auto-purged — they are the compliance record. Setting a value below 1,825 days (five years) logs a warning at startup because it may violate BSA record-retention if those rows are your only transaction record. Back up the FMS application database on the same schedule as your other books and records.

## FinCEN National AML/CFT Priorities

The first government-wide AML/CFT Priorities (FinCEN, June 30, 2021) — and FinCEN's 2026 AML/CFT Program rule proposal, which would require institutions to incorporate them into a documented risk assessment — cover eight areas. FMS maps its detection signals to them honestly (also live at `GET /rules` → `national_priorities`):

| Priority | FMS coverage | How |
|---|---|---|
| Corruption | Screening | OFAC programs (incl. Global Magnitsky); optional PEP list for EDD |
| Cybercrime (incl. virtual currency) | Partial | Account-takeover typology; no virtual-asset-native analytics |
| Terrorist financing | Screening | OFAC counter-terrorism programs on every party |
| Fraud | **Direct** | Behavioral deviation, invoice fraud, account takeover, velocity, odd hours |
| Transnational criminal organizations | Partial | Structuring/smurfing/velocity — the laundering mechanics; attribution is human work |
| Drug trafficking organizations | Partial | Structuring + multi-source smurfing (classic placement patterns); OFAC narcotics programs |
| Human trafficking & smuggling | Partial | Funnel-style multi-source inflow detection; FinCEN HT advisory indicators not modeled |
| Proliferation financing | Screening | OFAC SDN + Consolidated non-proliferation programs |

"Partial" is deliberate honesty: a transaction monitor sees money movement, not predicate crimes. FMS surfaces the mechanics and the officer attributes them.

## Access control & dual control (maker-checker)

FMS enforces role-based access (**admin** — full access including Administration; **analyst** — view and act on cases; **viewer** — read-only) and audits every sensitive action (logins, failed logins, case actions, password changes and resets, user changes, settings changes) with actor, target, timestamp, and IP.

Sensitive administrative changes are additionally under **dual control**: when the institution has two or more active admins, creating a user, changing a role, enabling/disabling an account, resetting another admin's password, or changing system settings does not take effect until a **second, different admin approves it** (Administration → Users → Pending Approvals). The requester can never approve their own change. With fewer than two active admins, changes apply immediately and the UI says so — institutions should create a second admin promptly; dual control activates automatically the moment they do.

Bootstrap is intentional: the **first account** created becomes the admin (in production this requires the setup token), and public self-signup is disabled after that — all further accounts are created by an admin from Administration → Users, with a temporary password delivered by email (or shown once on-screen when SMTP isn't configured).

## What FMS does *not* do

- It does not transmit anything to FinCEN or any regulator (no BSA E-Filing integration).
- It produces filing **worksheets** pre-filled from transaction data — not completed Forms 112/111. Subject identifiers, KYC details, and the final narrative require officer completion.
- It does not make final suspicious/not-suspicious determinations — a human officer does.
- It does not handle CTR exemptions (exempt persons) or recordkeeping retention; deadline tracking is informational, not enforced.

Use FMS to surface and organize; use your BSA/AML program to decide and file.
