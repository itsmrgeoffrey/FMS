# FMS Architecture

The system in one paragraph: FMS is a self-hosted transaction-monitoring platform — a FastAPI backend with a deterministic detection engine, a Next.js dashboard, and its own application datastore. Transactions enter one of two ways (API-push or read-only database polling); every transaction is scored by explicit rules, screened against sanctions lists, and — when flagged — becomes a case that a named human disposes. Nothing leaves the host by default.

## Components

```
                     ┌────────────────────────────────────────────────────┐
 institution systems │                    FMS backend (FastAPI, :8002)    │
 ────────────────────┤                                                    │
  MODE A: API-push   │  /ingest/transactions ─┐                           │
  POST + X-API-Key ──┼────────────────────────┤                           │
  (verdict returned  │                        ▼                           │
   synchronously)    │              Deterministic risk engine             │
                     │        (analyzer.py — rules, no ML in path)        │
  MODE B: DB poll    │                        │                           │
  read-only adapter ─┼──► poller.py ──────────┤                           │
  MySQL/MSSQL/       │                        ├── sanctions screening     │
  Postgres/Oracle    │                        │   (OFAC SDN + Consolidated│
                     │                        │    + PEP + extra lists)   │
                     │                        ├── CTR / SAR assessment    │
                     │                        ▼                           │
                     │                   FraudCase store                  │
                     │        (SQLite default · SQL Server/Postgres       │
                     │              via FMS_APP_DB_URL)                   │
                     │      │            │             │                  │
                     │      ▼            ▼             ▼                  │
                     │  REST API     WebSocket      signed callbacks      │
                     │  (/cases,     (/ws live      (case.flagged,        │
                     │  /reports,     feed)          case.disposition,    │
                     │  /rules, …)                   HMAC-SHA256) ────────┼──► institution
                     └──────┬─────────────────────────────────────────────┘     callback URL
                            │
                     Next.js dashboard (:3000) — /api/* proxied to :8002
```

## The two ingestion modes (`monitoring.mode` in bank_config.yaml)

**API-push (`api`, default, recommended).** The institution POSTs each transaction to `/ingest/transactions` with an `X-API-Key` and receives the full verdict synchronously (risk score, signals, CTR/SAR assessment, sanctions result). FMS holds **no credentials** to the institution's systems and opens no inbound path to them. Received transactions are stored in `ingested_transactions` as FMS's own history for behavioral baselines and backtesting.

**Database poll (`poll`).** For on-prem deployments: a read-only adapter (MySQL, SQL Server, PostgreSQL, or Oracle) polls the institution's transaction tables using the column mapping in `bank_config.yaml`, checkpointed per table in `processing_state` so restarts never re-process or skip. FMS never writes to the source database.

Outbound in both modes: optional **signed webhooks** — every delivery is HMAC-SHA256-signed over the raw body (`X-FMS-Signature`); the receiver recomputes the HMAC to verify authenticity and integrity. Best-effort with retries; failures never block case processing.

## Trust boundaries

1. **Institution ⇄ FMS ingestion:** authenticated (`X-API-Key`), no implicit trust by network position. In poll mode the only credential FMS holds is a **read-only** database user.
2. **Browser ⇄ API:** every route requires a signed bearer token (HMAC-signed, expiring; PBKDF2-SHA256 password hashes; per-IP login throttling). Role checks are enforced **server-side** on every endpoint — the UI's role-awareness is convenience, not the control.
3. **FMS ⇄ outside world:** by default, no external calls carry transaction data. Optional flows, each off until configured: SMTP alerts, signed callbacks to the institution's URL, OFAC list downloads from treasury.gov (data in, nothing out), and — only if enabled — an LLM endpoint for prose summaries, pointable at a self-hosted model.

## RBAC design

| Capability | Admin | Analyst | Viewer |
|---|---|---|---|
| View dashboards, cases, reports, rules, risk assessment | ✅ | ✅ | ✅ |
| Act on cases (confirm / dismiss / escalate / note) | ✅ | ✅ | — |
| Run 314(a) scans, access audit trail & security events | ✅ | — | — |
| Tune rules, run backtests, edit settings, manage users, edit/finalize risk assessments | ✅ | — | — |

Enforcement is in `backend/auth.py` dependencies (`require_user`, `require_admin`) applied per-router and per-endpoint. **Dual control (maker-checker):** when two or more active admins exist, sensitive admin changes (user creation, role changes, enable/disable, password resets of others, settings changes) queue as `pending_approvals` and execute only when a *different* admin approves; the requester can never approve their own change. With fewer than two admins, changes apply immediately and the UI says so.

Bootstrap: the first account becomes admin (production requires `FMS_SETUP_TOKEN`); public signup is disabled after that (`FMS_ALLOW_SIGNUP=false`). Optional LDAP / Active Directory sign-in federates authentication with group→role mapping (local accounts are tried first, then the directory).

## Storage

- **Application store** — FMS's own data (cases, users, audit, assessments…): SQLite out of the box; SQL Server or PostgreSQL via `FMS_APP_DB_URL` for production. Full table reference: [SCHEMA.md](SCHEMA.md).
- **Institution database** — poll mode only, read-only, never written to.
- **List data** (`data/`) — OFAC SDN + Consolidated JSON produced by `scripts/update_ofac.py`, optional `pep.json`, optional `extra_lists/*.json`.

Encryption at rest is deliberately delegated to the database engine / volume layer — rationale in [SECURITY.md](../SECURITY.md).

## Design positions (the why)

The load-bearing decisions — deterministic engine (no ML in the decision path), machine-flags/human-decides, data-stays-home, zero-trust-principled ingestion — are argued in full in the [whitepaper](WHITEPAPER.md) §2, with the detection methodology in [MODEL.md](../MODEL.md) and regulatory mapping in [COMPLIANCE.md](../COMPLIANCE.md).

## Stack

FastAPI + SQLAlchemy (async) · Next.js/TypeScript/Tailwind · pytest + GitHub Actions CI · Docker Compose. Backend binds :8002; frontend :3000 proxies `/api/*` to the backend (`BACKEND_URL`).
