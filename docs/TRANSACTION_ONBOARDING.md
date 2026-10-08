# Transaction Onboarding and History

Settings > Installation shows saved polling cursors, the history window and stored API transaction dates. This reads FMS's database, not the source: it does not certify complete history.

## Approvers

Enroll two named administrators belonging to different people through Settings > Users. A sole administrator can enroll the second through the existing bootstrap workflow. No account is created automatically. Rule and profile changes always require a different active administrator.

Settings > Approvals contains pending requests, configuration comparisons, reasons and recent decisions. The badge includes your own pending requests, not only requests you may approve. It refreshes after submissions and decisions, on tab changes or window focus, and every 30 seconds while Settings is open. A question mark means the count is unavailable, not zero. User-creation and password-reset approval results retain their one-time credential notice; deliver it securely before dismissing it or leaving the page.

## Database Polling

- On first connection with no checkpoint, FMS records the highest source ID in the same database order used by polling. Existing rows are baseline only, not individually assessed. Subsequent polls process higher IDs in ascending order.
- An empty source is initialized durably so its first arriving rows are processed, not skipped as a later baseline. This survives restart.
- Existing checkpoints are unchanged. Do not delete or reset them as an import mechanism.
- Source IDs must be unique, immutable and increasing in database sort order. Random UUIDs, lower-ID late inserts, reused IDs and updates to existing rows are not discovered reliably. Use an ordered upstream feed or API push for those sources.
- Inward and outward mappings use the shared read-only database by default. If the institution stores them separately, enable a per-feed database connection under Settings > System > Table Mappings (or add a nested `database` block to that table in `bank_config.yaml`). FMS connects to every configured source before a poll and merges account history from the feeds before running the same detection engine. A failed source connection therefore pauses database-poll analysis rather than silently assessing incomplete history.
- Account history is read from mapped source tables within the configured lookback relative to the current date. Analysis excludes other accounts, currencies and future transactions. Reading historical rows does not create historical assessments.

Before live use, verify mappings, cursor ordering, a known first post-baseline transaction, retry behavior and restart continuity against a representative test source. Reconcile source counts and amounts; connection status is not evidence of completeness.

## Supplying API History

There is no silent history-only importer. Historical transactions use authenticated `POST /ingest/transactions` and normal assessment, case creation and notifications.

1. Agree a coverage window and cutover with the institution; test representative data separately first.
2. Pause the live sender while loading the agreed history. Do not silently disable screening or review controls.
3. Send oldest first across feeds, preserving original timestamps with offsets, account IDs, account-holder IDs, currencies, directions, instruments, channels, cash classification, business dates, branch/location IDs and conductor details. Never omit historical timestamps: omitted timestamps use current time.
4. Await responses and resolve failures before advancing that account. Retry identical IDs and payloads. Reconcile receipts, counts and amounts by account, currency and day.
5. Resume live traffic after reconciling the cutover and assigning review responsibility. Late submissions do not rewrite later assessments. The earliest imported records have limited prior history; their results do not prove a fully populated baseline.

The configured lookback limits history considered for each assessment. Stored date ranges do not prove completeness. For older retrospective work, prefer API push: polling source history is relative to the current date.

## Collision-Free API IDs

The API has one deployment-wide namespace. Channel is transaction data, not an ID namespace. This change introduces no source registry or new credential system.

For new integrations, agree `system-prefix:original-transaction-id`, for example `core:12345` and `wallet:12345`. Institution-assigned prefixes must be stable and unique, without colons or whitespace; they are not hard-coded in FMS. Coordinate prefixes case-insensitively because database collations can differ. Preserve original IDs, including case and leading zeroes. The full ID must fit within 128 characters; if it cannot, maintain a stable unique upstream mapping instead of truncation or generating IDs per attempt.

Identical retries return the existing assessment; changed payloads return HTTP 409. Investigate collisions rather than generating a new ID to force acceptance. Existing unprefixed IDs remain valid: never rename or resend an already ingested transaction under a new prefix. Keep old retry IDs and establish a reconciled cutover for the new convention. Do not send the same transaction through both polling and API: their processing identities are separate and do not deduplicate across sources.
