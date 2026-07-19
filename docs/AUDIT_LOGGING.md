# Audit Logging

Everything an examiner would ask "who did that, and when?" about is written to the `audit_log` table with **actor, action, target, detail, IP, and timestamp**. Case dispositions additionally live in `case_actions` with the full note history. Audit rows are never auto-purged — they are part of the compliance record ([retention policy](../COMPLIANCE.md#record-retention)).

Recording is best-effort by design: an audit-write failure never blocks the underlying action (a monitoring system that refuses a login because its own log hiccuped would be a worse control). Writes happen server-side in the same code path as the action — there is no client-supplied audit data.

## Event catalog

**Authentication & account security**
| Action | Recorded when |
|---|---|
| `LOGIN` / `LOGIN_FAILED` / `LOGIN_RATE_LIMITED` | Every sign-in outcome, with IP; throttled attempts flagged |
| `SIGNUP` | Account self-registration (bootstrap only in production) |
| `PASSWORD_CHANGED` / `PASSWORD_RESET_REQUESTED` / `USER_PASSWORD_RESET` | Self-change · forgot-password request · admin reset of another user |
| `USER_CREATED` / `USER_ROLE_CHANGED` / `USER_ENABLED` / `USER_DISABLED` | User lifecycle (subject to dual control) |

**Case work**
| Action | Recorded when |
|---|---|
| `CASE_CONFIRMED_FRAUD` / `CASE_DISMISSED` / `CASE_ESCALATED` / `CASE_UNDER_REVIEW` / `CASE_NOTE_ADDED` | Every disposition/note, `target` = case id (mirrors `case_actions`) |
| `SANCTIONS_HIT` | A screening match forced a case — severity **critical** in the Security Events view |

**Reports & compliance artifacts**
| Action | Recorded when |
|---|---|
| `REPORT_CTR_ACCESSED` / `REPORT_SAR_ACCESSED` | Every report access, with format and row count — report *reads* are themselves audited |
| `314A_SCAN` | A 314(a) scan ran — **counts only, never subject names** (the list is confidential and never stored) |
| `RISK_ASSESSMENT_DRAFTED` / `_UPDATED` / `_FINALIZED` | Assessment lifecycle, `target` = version |
| `RETENTION_PURGE` | The optional purge job ran (actor `system`, with row counts) |

**Configuration & dual control**
| Action | Recorded when |
|---|---|
| `SETTINGS_UPDATED` | Any settings change (secrets summarized as "(changed)", never logged in value) |
| Rule parameter changes | Audited **and** recorded in the `rule_changes` tuning log with before/after values, rationale, and backtest evidence |
| `CHANGE_REQUESTED` / `CHANGE_APPROVED` / `CHANGE_REJECTED` / `CHANGE_CANCELLED` / `DUAL_CONTROL_INACTIVE` | Maker-checker lifecycle; `DUAL_CONTROL_INACTIVE` marks changes that applied directly because fewer than two admins existed |

**Ingestion security**
| Action | Recorded when |
|---|---|
| `INGEST_KEY_REJECTED` | A push with a wrong/missing `X-API-Key` — severity **warning** |

## Security Events view

`GET /audit/security` (admin-only, and in the UI under Audit Trail → Security events) filters the log to the security-relevant subset and assigns severities: **critical** (`SANCTIONS_HIT`) · **warning** (`LOGIN_FAILED`, `LOGIN_RATE_LIMITED`, `INGEST_KEY_REJECTED`) · **notice** (`USER_DISABLED`, `USER_ROLE_CHANGED`, `USER_PASSWORD_RESET`) · info (the rest), plus rolling counts of failed logins, rejected keys, and sanctions hits.

## Access control over the trail itself

Viewing the global audit log, per-user activity rollups (`GET /audit/users`), and security events requires **admin**. The IP field honors `X-Forwarded-For` only when `FMS_TRUST_X_FORWARDED_FOR=true` (set it only behind a proxy you control), so audit IPs can't be spoofed by a client header.
