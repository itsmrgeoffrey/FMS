# FMS Roadmap

The current phase repairs transaction assessment, review visibility, recovery, session handling, and dependency risks. Its boundaries and verification notes are in [Current Scope](docs/CURRENT_SCOPE.md).

The following are deliberately **deferred, not implemented or promised as current capabilities**:

1. **Investigation workspace:** case ownership, evidence, linked transactions, investigation timelines, and collaboration.
2. **Customer profiles:** verified customer identity, beneficial ownership, KYC risk, linked accounts, and customer-level aggregation.
3. **MFA:** enrollment, challenges, recovery, and administrator enforcement. Current session revocation is not MFA.
4. **Migrations and backups:** versioned schema upgrades, rollback planning, scheduled encrypted backups, restore drills, and disaster recovery.
5. **Configurable sources:** independent source registrations, credentials, field mapping, reconciliation, and source-level idempotency namespaces. Existing API and database adapters continue through the shared processor.
6. **UI polish:** a wider design-system, accessibility, responsive-layout, and interaction pass. This phase changes only correctness and visibility in existing workflows.
7. **Full reporting lifecycle:** officer determination, maker-checker filing approval, validated institution/customer data, filing packages, submission, acknowledgement, amendments, continuing-activity tracking, and evidence of completion.

Production readiness also requires institution-specific legal review, validation against representative data, and deployment/security testing. A functioning demonstration is not proof that these stages are complete.
