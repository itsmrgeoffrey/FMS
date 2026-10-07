# Small-Institution Setup

FMS supports transaction monitoring and human review for one institution per deployment. It is intentionally narrower than an enterprise AML suite. An installation check marked "Configured" is not a compliance certification, independent validation, or permission to go live.

## Configure the Installation

System, Rule Engine, Approvals, and Installation are administrator-only tabs under Settings. Direct links to `/rules` and `/setup` redirect to their Settings tabs. Analysts and viewers retain My Account only; configuration and tuning-history APIs also require an administrator.

1. Set the institution identity and ingestion mode in Settings > System. Use API push or the existing read-only database adapter. Payment channels are transaction data and use the same processor.
2. Confirm jurisdiction, institution type, and business timezone in Settings > Installation, with a recorded reason. Unsupported reporting scopes remain manual; changing a behavioural benchmark does not define local reporting law.
3. Map account identifiers, party names, amount, currency, timestamp, direction, channel, cash classification, and business date where available. Missing or unknown cash classification is not treated as non-cash. Source-supplied business dates take precedence over the configured timezone.
4. In Settings > Rule Engine, set behavioural benchmarks for the currencies the institution actually handles. Configure the structuring band, velocity window and smurfing window. The legacy API key name `ctr_thresholds` refers to behavioural benchmarks, not legal filing thresholds. Unconfigured currencies have no high-value benchmark; other detection and manual-review checks still apply.
5. Backtest the proposed values, review differences, and record the reason for the change. Edits invalidate the displayed preview. The server always reruns the replay when applying a change. An empty history requires explicit initial-configuration acknowledgement, not a claim of validation.
6. Assign named accounts to separate people. Rules and operating profiles always require a proposal from one active administrator and approval from a different active administrator. A sole administrator can submit a proposal, but it remains pending; there is no single-admin exception for detection configuration. Other administrative bootstrap actions retain their existing single-admin behaviour so a second administrator can be enrolled.

## Confirm Before Live Use

- Reconcile transaction counts and amounts against the source, including duplicates, late arrivals, and failed submissions. API IDs are unique within the shared API source; independent source credentials and namespaces are not yet implemented.
- Exercise normal activity, reporting-only reviews, missing data, arbitrary channels, duplicates, changed duplicate payloads, and above/below-benchmark activity with representative data.
- Keep enough history for the configured windows. The installation check compares configured history days, not actual completeness. Backtesting is capped and approximates history within the replay window; it does not replay sanctions screening or create cases.
- Verify full and fresh sanctions lists, investigate possible matches, and establish review ownership and escalation procedures.
- Verify HTTPS, restricted access, secrets, persistent storage, backup restoration, recovery, monitoring and timely review. Installation cannot verify these controls automatically. MFA and automated backup/migration tooling remain roadmap items.
- Validate institution-specific reporting duties with a qualified officer. FMS has account-level analysis, not verified person-level aggregation, ownership analysis, KYC, or a filing lifecycle. Report outputs and deadline reminders remain drafts/provisional aids.

## Storage and Operation

Run one backend worker and one replica. Rule/profile locks and processing coordination are not distributed. Frontend and backend should be upgraded together for the new configuration-version fields.

Initial rules come from defaults and `bank_config.yaml`. After a versioned rule save, the latest `RuleChange` snapshot in the application database is authoritative at startup. Operating profiles are restored from `PROFILE_UPDATED` audit records; environment values are bootstrap defaults until the first saved profile. Do not purge these records independently of the operational database. Include the database, bootstrap configuration, secrets and sanctions data in the institution's recovery procedures.

Failed configuration writes leave live settings unchanged. Profile changes and rule changes share a revision: stale proposals return 409 rather than overwriting newer settings. New assessments retain their operating profile and rule snapshot; historical assessments are not rewritten by tuning.

The protected configuration, approval decision and approval audit record commit together before activation. An inactive or demoted requester or approver, self-approval, a cancelled proposal, stale settings or a failed database write cannot apply the change. Approvers can inspect saved before/proposed values and the reason in Settings > Approvals. Other administrative actions and activity logging retain their existing transactional limitations.

These controls enforce distinct administrator accounts, not independently verified human identities. Do not share accounts or let one person control both approval identities. Restrict operating-system, database, deployment and configuration-file write access: someone with host/database control can change stored rules outside application permissions. MFA remains deferred; these safeguards are not a substitute for secure deployment and identity controls.

## Intentionally Deferred

Investigation workspaces, richer customer profiles, MFA, migration and backup automation, independent source registration, broader UI polish, and the full reporting lifecycle remain in [ROADMAP.md](../ROADMAP.md). The aim is a dependable, limited review tool, not an ultimate compliance platform.

See [Transaction Onboarding](TRANSACTION_ONBOARDING.md) for start-point semantics, historical loading, ID conventions and second-administrator enrollment.
