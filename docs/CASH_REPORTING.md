# Cash reporting and suspicious-activity assessment

FMS evaluates physical-cash CTR applicability separately from behavioral risk,
sanctions screening, and suspicious-activity review. These reporting rules cover
the configured US-bank, USD baseline. A candidate or recommendation is an officer
review item, not a submitted report or a legal filing determination.

## Expected routing

| Scenario | CTR assessment | Suspicious-activity assessment |
| --- | --- | --- |
| $12,000 physical cash deposit, nonexempt customer | CTR candidate | Independently risk-scored |
| $50,000 wire from existing balance | No CTR | Risk-scored |
| Two $6,000 cash deposits at different branches, same holder or conductor, same business day | $12,000 aggregate; CTR candidate | Possible cross-branch structuring |
| $4,000 wire inconsistent with account behavior | No CTR | May alert; amount alone does not mandate a SAR |
| $100,000 routine business wire with supporting history | No CTR | Can remain low-risk |
| $15,000 physical cash deposit within a valid approved exemption | Recorded exemption applied | Monitoring remains active |

The CTR trigger is strictly **more than $10,000**, including exact decimal
aggregation. Cash in and cash out are assessed separately; they are never netted.
The tunable behavioral benchmark does not change this statutory baseline.
Cash at an ATM or another channel is still cash when explicitly classified as
such. Channel names do not establish the classification.

## Source contract

API ingestion and all four database adapters use the same normalized fields:

| Field | Meaning |
| --- | --- |
| `is_cash` | Explicit physical-cash boolean; missing classification needs manual reporting review |
| `account_holder_id` | Stable institution-wide identity of the account holder, consistent across accounts and feeds |
| `conductor_id` | Stable identity of the person presenting or conducting the cash transaction |
| `branch_id`, `location_id` | Distinct branch/location identifiers for cross-branch pattern checks |
| `business_date` | Optional source banking date; otherwise derived from the institution's business timezone |
| `acting_as_agent` | Whether the account holder is acting for another beneficial owner; only explicit `false` permits an exemption |
| `cash_purpose` | `PAYROLL` or `OTHER`; a payroll exemption requires `OUTWARD` and `PAYROLL` |

Map these fields in Settings > System > Table Mappings for each applicable feed.
The simulator exposes cash scope fields under Test details for cash transactions.
Stable holder/conductor IDs must be mapped consistently across sources. FMS does
not infer identity from a shared name, perform fuzzy entity resolution, or infer
that a holder ID and a conductor ID from different identifier systems are the
same person. Account, holder, and conductor groups remain separate, with source
transaction deduplication in each group. Unrelated groups are not combined into
an invented person-level total. Known cross-role relationships or missing IDs
require institution review and upstream identity normalization.

Behavioral profiles remain specific to the account and currency. Related-party
cash history adds CTR and cross-branch checks without changing an unrelated
account's average transaction size or known beneficiaries.

## Exemption administration

1. An administrator opens Settings > CTR Exemptions and proposes a record.
2. The record identifies the holder, covered accounts, exemption category,
   effective/expiry dates, eligibility review dates, evidence reference, and
   eligibility basis. Categories requiring designation also require a recorded
   FinCEN designation reference.
3. The requester attests that the institution verified eligibility. Another
   active administrator reviews the full proposal in Settings > Approvals.
4. Approval activates the record and records both identities in the audit trail.
   A single-admin installation cannot activate an exemption by itself.
5. Revocation also requires a recorded reason and independent approval. A
   pending revocation has not yet disabled the record.

FMS stores the institution's verified determination; it does not independently
validate corporate eligibility or submit a Designation of Exempt Person to
FinCEN. A reference alone is not proof that the legal requirements are met.
The local record validity is conservatively limited to the next review date,
no more than 365 days after the recorded eligibility review, for every category.

Only an active, approved record matching the exact holder, account, banking date,
and transaction scope is applied. Expired, revoked, future-effective, unmatched,
agent, and unknown-agent cases receive no exemption. Payroll-customer exemptions
cover only cash withdrawals for payroll. Exemptions do not disable sanctions,
behavioral risk, structuring, or SAR review. API callers cannot set an exemption
flag to bypass administrator approval.

## Evidence and historical activity

Each processing assessment stores the cash grouping basis, exact gross and
nonexempt totals, contributing source transaction IDs, and applied exemption ID
and approving administrator. Case detail exposes this under Cash reporting
evidence. Historical assessments and idempotent retries keep their original
recorded result even if an exemption is later revoked.

On startup, FMS creates the new cash-index and exemption tables through its
existing schema initialization and backfills the index from completed exact
processing snapshots. Only previously received transactions with explicit cash
classification and available IDs can contribute to cross-account aggregation.
Legacy rows lacking those facts cannot be reconstructed automatically. Historical
source transactions must be ingested with their original timestamps and stable
IDs; merely connecting a database does not supply its entire history.

Future-dated activity is excluded from the historical score. A late-arriving
transaction with subsequent account or related-party cash activity is marked for
manual review of affected daily totals. Earlier cases are not silently rewritten
or retroactively filed. Rule backtests use available history within the replay
window and the current approved exemption records; they are simulations, not
reproductions of every historical configuration.

Shared account/party locks prevent concurrent linked submissions from observing
incomplete histories in the supported **single-worker** deployment. Multi-worker
distributed locking and large-volume performance qualification are not established
by these changes.

## Verification and authority

`tests/test_cash_reporting.py` covers the six scenarios, strict monetary boundary,
duplicate protection, separate cash directions/dates/currencies, unrelated groups,
concurrent sources, startup backfill, late arrivals, exemption scope and revocation,
independent approval, API role restrictions, and source-adapter field mapping.
Adapter tests exercise normalization contracts, not live bank database connections.

Government sources underpinning the reporting baseline:

- [31 CFR 1010.311: currency transaction reporting](https://www.ecfr.gov/current/title-31/subtitle-B/chapter-X/part-1010/subpart-C/section-1010.311)
- [31 CFR 1010.313: aggregation](https://www.ecfr.gov/current/title-31/subtitle-B/chapter-X/part-1010/subpart-C/section-1010.313)
- [31 CFR 1020.315: exempt persons, designation, limitations, and continuing monitoring](https://www.ecfr.gov/current/title-31/subtitle-B/chapter-X/part-1020/subpart-C/section-1020.315)
- [31 CFR 1020.320: bank suspicious-activity reporting](https://www.ecfr.gov/current/title-31/subtitle-B/chapter-X/part-1020/subpart-C/section-1020.320)
