# Current Scope and Operational Limits

This document supersedes older pipeline excerpts and regulatory claims in the July 2026 design papers. FMS is a review aid, not a validated compliance system, payment processor, or report-filing service.

## Implemented

- API pushes, the simulator, and database polling use one resumable processor. Channels are transaction data, not separate decision engines. The supplied account is preserved.
- Normalization validates positive, finite decimal amounts and UTC timestamps. Analysis uses prior same-account, same-currency history only. New processing snapshots preserve exact amounts; legacy case and raw-transaction amount columns remain floating point pending a reviewed schema migration.
- Same-account submissions are serialized within the supported single-worker process. Repeated source/transaction IDs return the existing assessment; changed payloads return HTTP 409. API identifiers remain global to the existing API source: independent source registrations and credentials are deferred.
- A durable processing record precedes analysis. Case creation, completion state, and notification enqueue commit together. Interrupted API submissions retry automatically, up to ten attempts; admin endpoints expose failures and permit another retry. Polling retries without advancing past a failed transaction.
- Callback, email, and webhook deliveries are persisted with backoff. Delivery is at least once, not exactly once; callback consumers should deduplicate `delivery_id`. WebSocket updates are best effort; the database-backed queue is authoritative.
- Detection, screening, regulatory assessment, and case disposition are shown separately. CTR-only, incomplete-screening, and manual-assessment items remain reviewable. Legacy CLEAN cases with reporting flags and escalated cases remain in the review queue. Closing a case does not erase its reporting flags.
- References such as `payroll` and unverified batch IDs cannot lower the score. Rule settings are validated before mutation. Backtesting prefers exact processing snapshots from both API and polled transactions.
- Account-holder and counterparty screening use the same path. Name matches are candidates for identity verification. Missing names, unusable lists, and stale lists require review, never an implied clean screening result. List freshness is checked against twice the configured refresh interval, with a 24-hour minimum.
- Logout revokes the token. Password, role, and active-status changes invalidate older sessions. WebSockets recheck authorization before sending case data. Existing sessions must sign in again after this update.
- Alerts and Transactions use server-side filters and pagination, with visible load errors. The simulator displays an assessment, not a successful funds transfer.
- Dashboard puts highest-risk open reviews first and labels current versus all-time indicators. Alerts supports full-queue account/source/reference search, status, reporting flags, minimum risk, and sorting; mobile entries show amount, flags, risk and status without a wide table. Transaction Details separates detection, screening and reporting, exposes source identifiers, and asks for confirmation before terminal dispositions. Existing colours and navigation are retained. Investigation workspaces and report filing are still deferred.

## Installation and Tuning

The Installation screen records institution type, jurisdiction and IANA business timezone, and distinguishes configuration checks from unverified operating controls. Rule Engine opens read-only; administrators can propose changes to currency benchmarks and detection windows. Every rule/profile proposal requires a different active administrator's approval, even with only one admin enrolled. Both accounts must still be active admins when applying the change. A reason, current configuration revision and server-run replay are required; no-history initial configuration requires explicit acknowledgement. The protected change, approval decision and approval audit record commit together. Stale or cancelled proposals are rejected, failed database writes do not change live configuration, and saved snapshots are restored on restart. New transaction assessments include their operating profile alongside their rule snapshot.

See [Small-Institution Setup](SMALL_INSTITUTION_SETUP.md) for storage precedence, onboarding checks and boundaries. No new schema migration or automatic regulatory regime has been added.

The mandatory-approval hardening passed 108 backend tests, TypeScript checking and a production build. Local browser checks confirmed read-only thresholds, single-admin proposals remaining pending without changing live values, no self-approval action, and cancellation. The existing render-time ref access in Administration still triggers its React lint rule; Rule Engine passes focused lint. This is application-level access control, not protection against a host/database administrator or shared approval accounts.

## Reporting Scope

The supported automatic assessment is a **US bank / USD** review rule, selected by `REGULATORY_JURISDICTION=US` and `INSTITUTION_TYPE=bank`. Other combinations require manual reporting assessment; no FX conversion or foreign law is inferred.

`is_cash=true` is required for automatic CTR assessment. Cash **strictly above USD 10,000**, either individually or as a same-direction business-day total for the monitored account, creates a CTR review flag. Exactly USD 10,000 alone does not. `is_cash=false` does not trigger CTR; missing classification requires review. `business_date` can carry the source's banking date; otherwise `BUSINESS_TIMEZONE` (default UTC) determines the date. Cash-in and cash-out are not netted.

Account-level aggregation is incomplete regulatory coverage: related-person accounts, on-behalf-of relationships, exemptions, and foreign-currency cash conversion still need officer verification. Late-arriving transactions are flagged for manual reconciliation of affected totals; historical cases are not silently rewritten.

Suspicious USD activity involving at least USD 5,000 is surfaced for a bank officer's SAR assessment. This is not an automatic legal filing decision or complete coverage of all mandatory/voluntary SAR categories. Pattern alerts can exist below that amount without asserting a mandatory SAR. Behavioral currency benchmarks and the legacy `sar_ratio` configuration do not alter these assessment amounts.

Existing report exports and date reminders are drafts. FMS does not know the legally established initial-detection date, filing approval, submission, acknowledgement, amendment, or continuing-activity status. Case dismissal does not prove an obligation was satisfied. The full reporting lifecycle is deferred.

Sources: [FinCEN CTR FAQs](https://www.fincen.gov/resources/frequently-asked-questions-regarding-fincen-currency-transaction-report-ctr), [aggregation guidance](https://www.fincen.gov/resources/statutes-regulations/guidance/currency-transaction-report-aggregation-businesses-common), and [bank SAR rule, 31 CFR 1020.320](https://www.ecfr.gov/current/title-31/subtitle-B/chapter-X/part-1020/subpart-C/section-1020.320). Institutions must verify current requirements with their compliance officer.

## Deployment and Verification

Run **one backend worker and one replica**. Account serialization, poller ownership, and the delivery loop are not distributed locks. Multi-worker deployment is not supported by this change.

Existing polling bootstrap behavior is unchanged: a new checkpoint starts at the latest source ID and monitors subsequent rows, rather than replaying the entire bank history. Source cursor assumptions and historical reconciliation must be verified during integration.

The existing startup schema mechanism creates three additional tables: `transaction_processing`, `notification_deliveries`, and `revoked_sessions`. No migration framework or backup automation has been built. Validate the upgrade on a copy of the institution's database before deployment; this change has been exercised against SQLite, not live Oracle, SQL Server, MySQL, or PostgreSQL services.

Useful checks:

```text
python -m pytest -q
python -m pip_audit --progress-spinner off
cd frontend
npx tsc --noEmit
npm run build
npm audit --omit=dev
```

The Python environment audit and frontend production-dependency audit reported zero known vulnerabilities during this change. The full npm audit still reports a development-only `braces` advisory (GHSA-vfj7-8cjw-p6xm) through ESLint's dependency chain; no compatible patched release was available. Production Docker output uses Next's standalone bundle rather than copying all development dependencies. Recheck advisories before release.

See [ROADMAP.md](../ROADMAP.md) for features intentionally not built in this phase.

The small-institution configuration pass passed 100 Python tests against an isolated SQLite configuration, a production frontend build, and focused lint on Rule Engine and Installation. Coverage includes required rationale, stale proposals, failed configuration writes, server-owned replay evidence, restart restoration, privilege checks and second-person approval. Browser verification used a separate synthetic-data database and checked profile scope, currency additions, preview invalidation, recorded changes and mobile layouts. Server-database compatibility and real institution workflows still need deployment-specific verification.

Focused lint checks cover Dashboard, Alerts, Transaction Details, and their changed shared controls. The UI pass passed the production build and 88 Python tests, including server-filter and dashboard-contract coverage. Local browser checks cover desktop/mobile layouts, search, filter/reset behaviour, decision confirmation and review audit updates using synthetic data. The pre-existing synchronous state initialization in `AppShell` still fails the stricter React effect lint rule; a broad UI cleanup remains deferred. A successful production build is not a claim that every existing lint warning or UI issue has been resolved.
