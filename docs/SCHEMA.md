# FMS Application Database Schema

The application datastore (SQLite by default; SQL Server/PostgreSQL via `FMS_APP_DB_URL`) holds FMS's own records — cases, users, audit, assessments. It is entirely separate from any institution transaction database, which FMS only ever reads (poll mode) or never touches (API mode). Source of truth: [`backend/models.py`](../backend/models.py); tables are created automatically at startup.

## fraud_cases — one row per flagged (or CTR-triggering) transaction
The compliance record at the center of everything. Unique on `(source_table, source_txn_id)` so replays/crash-recovery can never create duplicate cases.

| Column group | Columns | Notes |
|---|---|---|
| Identity | `id` (uuid), `source_table` (`inward`/`outward`/`api`), `source_txn_id` | Idempotency pair |
| Transaction | `account_id`, `amount`, `direction`, `timestamp`, `counterparty_account`, `counterparty_name`, `channel`, `currency`, `reference` | Normalized fields |
| Analysis | `risk_score` (0–100), `confidence` (HIGH/MEDIUM/LOW), `fraud_type`, `reasons` (JSON — every signal with its numbers), `ai_summary` | Fully deterministic; `ai_summary` is prose only |
| Obligations | `ctr_required` + `ctr_reason`, `sar_recommended` + `sar_reason`, `sanctions_hit` + `sanctions_detail` | The regulatory flags |
| Workflow | `status` (OPEN / UNDER_REVIEW / CONFIRMED_FRAUD / DISMISSED / ESCALATED / CLEAN), `created_at`, `updated_at` | `created_at` = detection date for the SAR 30-day clock |

## case_actions — the disposition history
Every analyst action on a case: `case_id` (FK), `action` (OPENED / DISMISSED / CONFIRMED / ESCALATED / REVIEW / NOTE_ADDED), `actor` (named user), `note`, `created_at`. Append-only in practice — dispositions are recorded, not rewritten.

## users
`id` (uuid), `username`, `email`, `full_name`, `password_hash` (PBKDF2-SHA256 — plaintext never stored), `role` (admin/analyst/viewer), `is_active`, `created_at`, `last_login_at`. LDAP/AD users are auto-provisioned here with directory-mapped roles.

## audit_log — the examiner-facing trail
`id`, `username`, `action` (catalog in [AUDIT_LOGGING.md](AUDIT_LOGGING.md)), `target` (case id / user / resource), `detail`, `ip`, `created_at`. Written best-effort on every sensitive action; never auto-purged.

## pending_approvals — dual control (maker-checker)
Sensitive admin changes awaiting a second admin: `action` (USER_CREATE / USER_SET_ROLE / …), `payload` (JSON for the executor), `target`, `summary`, `requested_by`/`requested_at`, `status` (pending/approved/rejected/cancelled), `decided_by`/`decided_at`, `decision_note`. The requester can never be the decider.

## risk_assessments — versioned institutional ML/TF risk assessment
`id`, `version`, `status` (DRAFT/FINAL), `title`, `categories` (JSON — area/item/inherent/controls/residual/notes rows), `priorities` (JSON — the eight National Priorities checklist), `activity_snapshot` (JSON — auto-filled "reports filed" data), `overall_rating`, `summary`, `created_by`/`created_at`, `updated_at`, `finalized_by`/`finalized_at`. FINAL versions are immutable; a new draft carries the previous version forward.

## rule_changes — the tuning log
FFIEC "documented and periodically reviewed" evidence, generated as a side effect of use: `changed_by`, `changed_at`, `old_values` (JSON), `new_values` (JSON), `rationale`, `backtest` (JSON summary of the pre-save replay).

## ingested_transactions — API-push history store
Transactions received via `/ingest/transactions` (unique on `external_id`): the normalized transaction fields plus `account_holder_name` and `received_at`. Serves behavioral baselines, 314(a) scans, and rule backtesting. This is the **only** table the optional retention purge (`FMS_RETENTION_DAYS`) ever touches.

## processing_state — poll-mode checkpoints
`table_key`, `last_processed_id`, `last_processed_at`, `updated_at`. Checkpoints advance only after a case is durably committed — a monitoring gap is treated as worse than a processing delay.

---

**Portability note:** string columns carry explicit lengths and JSON columns use the SQLAlchemy JSON type, so the same models run on SQLite, SQL Server, and PostgreSQL unchanged. **Retention:** cases, actions, audit rows, and assessments are never auto-deleted ([COMPLIANCE.md](../COMPLIANCE.md#record-retention)).
