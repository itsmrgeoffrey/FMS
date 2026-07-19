# FMS Deployment Guide

Three ways to run it, one configuration model. Start with the demo, promote to production deliberately.

## 1. Pick your mode

| | Demo / evaluation | Production (API-push) | Production (DB-poll) |
|---|---|---|---|
| Transactions come from | seeded SQLite / `/ingest` | your systems POST to `/ingest/transactions` | read-only polling of your core banking DB |
| App datastore | SQLite | SQL Server / PostgreSQL (`FMS_APP_DB_URL`) | SQL Server / PostgreSQL |
| bank_config.yaml | not needed | optional (`monitoring.mode: api`) | required (`mode: poll` + DB + column mapping) |
| Secrets | fixed demo values | real, rotated | real, rotated |

The two-minute demo is in the [README](../README.md#try-it-in-2-minutes-demo-mode). For the ingestion-mode decision itself, see [ARCHITECTURE.md](ARCHITECTURE.md#the-two-ingestion-modes-monitoringmode-in-bank_configyaml).

## 2. Configuration model

Two files, both selectable per environment so prod/test never collide:

- **`.env`** — secrets and switches (table below). Which file loads is chosen by `FMS_ENV_FILE` (default: project root `.env`).
- **`bank_config.yaml`** — ingestion mode, DB mapping, institution details, integrations. Chosen by `FMS_BANK_CONFIG` (default: root). Template: [`bank_config.example.yaml`](../bank_config.example.yaml). Admin-UI settings changes persist to whichever files the process loaded.

A clean environment split is simply two launch scripts exporting different `FMS_ENV_FILE` values (the repo's committed `test/` folder is a worked example — safe demo env, seeded SQLite, no real secrets).

### Environment variable reference

| Variable | Default | Purpose |
|---|---|---|
| `FMS_ENV_FILE` | root `.env` | Which env file this process loads |
| `FMS_BANK_CONFIG` | root `bank_config.yaml` | Which bank config this process loads |
| `FMS_APP_DB_URL` | *(empty → SQLite)* | Application datastore: `mssql+aioodbc://…` or `postgresql+asyncpg://…` |
| `FMS_DB_PATH` | `fms.db` | SQLite path when `FMS_APP_DB_URL` is empty |
| `FMS_AUTH_SECRET` | **set in production** | Signs session tokens — long random value, keep secret |
| `FMS_AUTH_TOKEN_TTL_HOURS` | `12` | Session lifetime |
| `FMS_ALLOW_SIGNUP` | `true` (dev) | Set `false` in production after first admin |
| `FMS_SETUP_TOKEN` | — | Required to create the first admin when signup is disabled |
| `FMS_INGEST_API_KEY` | — | The `X-API-Key` for `/ingest/transactions` — rotate from any demo value |
| `FMS_API_KEY` | — | Optional API key gate for shared deployments |
| `FMS_OFAC_REFRESH_HOURS` | `24` | Auto-refresh cadence for OFAC lists (0 = manual via `scripts/update_ofac.py`) |
| `FMS_RETENTION_DAYS` | `0` (off) | Optional purge of raw ingested rows only — never cases/audit; warns under 1825 days (BSA 5-year) |
| `FMS_LOG_LEVEL` / `FMS_LOG_FILE` | `INFO` / console | Logging level and optional rotating file |
| `FMS_AI_SUMMARIES` | `off` | Opt-in LLM prose summaries (never in the decision path) |
| `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY` / `GROQ_API_KEY` | — | Only if AI summaries are enabled; point `LLM_BASE_URL` at a self-hosted model to keep prose on-host |
| `GMAIL_USER` / `GMAIL_APP_PASSWORD` / `ALERT_EMAIL` | — | Optional email alerts |
| `ALERT_WEBHOOK_URL` | — | Optional alert webhook |
| `FMS_TRUST_X_FORWARDED_FOR` | `false` | Set `true` only behind a proxy you control (audit-log IPs) |
| `FMS_ENV` | — | Environment label shown in system info |

## 3. Run it

**Docker (recommended):**
```bash
cp .env.example .env                          # fill in secrets
cp bank_config.example.yaml bank_config.yaml  # pick mode; fill DB block only for poll mode
docker compose up -d                          # backend :8002, frontend :3000
```
Host-machine DB from a container: use `host.docker.internal`. MSSQL Windows Authentication doesn't cross the Linux container boundary — use a SQL-auth (still read-only) user.

**Manual:** Python 3.11+, Node 18+ — `pip install -r requirements.txt`, `uvicorn backend.main:app --port 8002`, `cd frontend && npm run dev` (set `BACKEND_URL` if the backend isn't on `localhost:8002`). Schema is created automatically at startup; no migration step for a fresh install.

## 4. Production checklist

- [ ] `FMS_APP_DB_URL` → server database (SQL Server/PostgreSQL), not SQLite; engine/volume encryption on (see [SECURITY.md](../SECURITY.md))
- [ ] Strong `FMS_AUTH_SECRET`; `FMS_INGEST_API_KEY` rotated from any demo value and shared only with the sending institution
- [ ] First admin created via `FMS_SETUP_TOKEN`, then `FMS_ALLOW_SIGNUP=false`; second admin added so dual control activates
- [ ] Poll mode: dedicated **read-only** DB user; API mode: no DB credentials to hold at all
- [ ] TLS terminated in front (reverse proxy); backend not exposed raw to the internet; `FMS_TRUST_X_FORWARDED_FOR=true` behind that proxy
- [ ] OFAC refresh running (built-in `FMS_OFAC_REFRESH_HOURS` or a scheduled `python scripts/update_ofac.py`)
- [ ] Institution details + callback URL/secret set (Administration → Institution / API Integrations)
- [ ] Application database backed up on your books-and-records schedule (BSA 5-year retention — [COMPLIANCE.md](../COMPLIANCE.md#record-retention))
- [ ] Never run `scripts/seed_demo.py` against production (it refuses non-SQLite targets, but don't try)

## 5. Upgrades & operations

`git pull` → restart backend (new columns/tables are created at startup; existing data untouched) → rebuild frontend. Watch `/health` for poller/bank-DB status, the Audit Trail's Security Events view for anomalies, and the logs (`FMS_LOG_FILE`) for `RETENTION_PURGE` / OFAC-refresh outcomes. Single-node by design — the scale story and its boundaries are stated honestly in the [README](../README.md#deliberate-scope-boundaries).
