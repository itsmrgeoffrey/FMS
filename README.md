# FMS — Fraud Monitoring System

**Open-source, real-time transaction monitoring and BSA/AML reporting for the institutions that can't afford enterprise compliance suites.**

Community banks, credit unions, money services businesses, and fintech startups carry the same Bank Secrecy Act obligations as the largest banks — Currency Transaction Reports, Suspicious Activity Reports, structuring detection — but rarely have the budget for six-figure AML platforms. FMS is a self-hostable system that watches a transaction database in real time, scores each transaction against a transparent risk engine, and produces the CTR and SAR filing lists a compliance officer needs. It is built to US FinCEN / BSA standards and runs on hardware you already have.

> **Not legal or compliance advice.** FMS is a decision-support tool. It flags activity and prepares filing lists; it does **not** file reports and does **not** replace a qualified BSA/AML officer's judgment. All filings remain the institution's responsibility. See [COMPLIANCE.md](COMPLIANCE.md).

---

## Why this matters

Financial-crime detection protects the integrity of the payment system — money laundering, terrorist financing, elder fraud, and structuring all move through the under-resourced institutions least able to detect them. Making credible, standards-aligned monitoring available as open source lowers that barrier.

## What it does

- **Two first-class ingestion modes** — **API push** for partners who won't share database access (they `POST /ingest/transactions` with API-key auth and receive the risk verdict synchronously), **or database poll** for in-house/on-prem deployments where FMS reads your core banking database read-only (MySQL, SQL Server, PostgreSQL, Oracle). Outbound webhooks/callbacks work in both.
- **Transparent risk engine** — a fully deterministic scorer (no black box) covering:
  - Near-threshold "structuring" amounts and repeated near-misses
  - Velocity clustering across a rolling window
  - Inbound multi-source "smurfing" and same-counterparty accumulation
  - Behavioral deviation from an account's own baseline
  - New counterparty / new channel / odd-hours signals
  - Payroll/batch suppression so legitimate bulk runs don't false-positive
- **Sanctions & watch-list screening** — every party is screened against the OFAC SDN list (block-or-reject case regardless of risk score) and the OFAC Consolidated non-SDN lists (review-required case), both refreshed by `scripts/update_ofac.py`. Bring-your-own lists (UN/EU/UK or internal) via `data/extra_lists/*.json`, plus optional PEP list support (`data/pep.json`) for enhanced-due-diligence flags.
- **FinCEN 314(a) batch scan** — upload the 314(a) subject list and FMS scans it against every account holder and counterparty it has seen (in memory; the list is never stored). Positive matches are the institution's to verify and report via FinCEN's SISS.
- **Institutional risk assessment** — the documented, versioned ML/TF risk assessment FinCEN's 2026 Program rule proposal **would require** (proposed, not yet final — but the direction of travel): a rated category grid (products/customers/geographies/channels), the National AML/CFT Priorities checklist pre-mapped to FMS detection coverage, and an activity snapshot auto-filled from your own case data. FMS structures it; the ratings are the officer's.
- **Rule backtesting + tuning log** — test a threshold change against your stored history ("what would this have flagged?") before saving it; every change is recorded with before/after values, actor, rationale, and the backtest evidence — the documented-review trail examiners ask for.
- **CTR assessment** — single-transaction and same-day aggregate detection against currency-aware thresholds (FinCEN USD $10,000 and local equivalents).
- **SAR assessment** — recommends a Suspicious Activity Report for structuring/smurfing (any amount) and for suspicious activity at/above the SAR threshold, with **30-day filing-deadline tracking**.
- **FinCEN filing worksheets + draft batch XML** — `/reports/ctr?format=fincen` and `/reports/sar?format=fincen` emit Form 112 / Form 111 field structures pre-filled from transaction data, with explicit lists of what still needs KYC records and officer review. `?format=xml` produces a **draft** batch file structured after the FinCEN E-Filing format, with every incomplete item marked — the officer completes it and validates it in FinCEN's batch validator before upload.
- **Plain-English case summaries** — an LLM writes an officer-readable explanation, with a **deterministic fallback** so an AI outage never blocks a case from being created. Point `LLM_BASE_URL` at a local OpenAI-compatible endpoint (e.g. Ollama) and no transaction data leaves your infrastructure.
- **Case management + audit trail** — open / under-review / confirmed / dismissed / escalated, every action attributed to a named actor.
- **Filing exports** — `/reports/ctr` and `/reports/sar` as JSON or CSV, ready to hand to your filer.
- **Live dashboard** — Next.js UI with a real-time alert feed (WebSocket), filtering, and per-case detail.
- **Alerting** — optional email alerts on new fraud cases.
- **Optional API-key auth** — lock down the API for production with a single environment variable.

## Architecture

```
Core banking DB ──(read-only adapter: MySQL / MSSQL)──▶ Poller
                                                          │
                                            Deterministic risk engine
                                            + CTR/SAR assessment
                                            + LLM summary (with fallback)
                                                          │
                                     Case store (SQLite) ──┬──▶ REST API (FastAPI, :8002)
                                                           │       ├─ /cases, /reports/{ctr,sar}
                                                           │       └─ /ws (live feed)
                                                           └──▶ Next.js dashboard (:3000)
```

FMS only ever **reads** from your banking database. Its own case data lives in a separate SQLite store.

## Try it in 2 minutes (demo mode)

Demo mode is fully self-contained — SQLite app store, API-push ingestion, **no bank database and no real credentials anywhere**:

```bash
pip install -r requirements.txt
FMS_APP_DB_URL= FMS_DB_PATH=fms_demo.db python scripts/seed_demo.py
FMS_APP_DB_URL= FMS_DB_PATH=fms_demo.db python -m uvicorn backend.main:app --port 8002
# in a second terminal:
cd frontend && npm install && npm run dev    # open http://localhost:3000
```

Sign in with the seeded demo users (each shows a different permission level):

| Role | Email | Password |
|---|---|---|
| Admin | `admin@fms.demo` | `DemoAdmin!2026` |
| Analyst | `analyst@fms.demo` | `DemoAnalyst!2026` |
| Viewer | `viewer@fms.demo` | `DemoViewer!2026` |

The seed includes sample cases across the detection typologies (structuring, smurfing, invoice fraud, account takeover, an OFAC match, plus confirmed/dismissed outcomes) so every dashboard, report, and KPI has content.

> **Demo vs. production:** these credentials exist **only** in a database you seed yourself locally — they are not baked into the application and cannot log in to any real deployment. For production, point `FMS_APP_DB_URL` at your server database, create your own `bank_config.yaml` (never committed), keep `FMS_ALLOW_SIGNUP=false` with a `FMS_SETUP_TOKEN` for first-admin bootstrap, and never run `seed_demo.py` against it (the script refuses non-SQLite databases).

## Quickstart (Docker — recommended)

**Requirements:** Docker, and read access to a MySQL or SQL Server transaction database.

```bash
cp .env.example .env                            # add keys as needed
cp bank_config.example.yaml bank_config.yaml    # point at your database (read-only user)
docker compose up -d
# open http://localhost:3000 — finish configuration on the Settings page
```

Connecting to a database on the host machine: use `host.docker.internal` as the host in `bank_config.yaml`. MSSQL Windows Authentication doesn't work from a Linux container — use a SQL-auth user instead.

## Quickstart (manual)

**Requirements:** Python 3.11+, Node 18+, and read access to a MySQL or SQL Server transaction database.

```bash
# 1. Backend
pip install -r requirements.txt
cp .env.example .env                     # add your GROQ_API_KEY (summaries) and optional alert settings
cp bank_config.example.yaml bank_config.yaml   # point at your database (read-only user)
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8002

# 2. Frontend
cd frontend
npm install
npm run dev                              # http://localhost:3000

# 3. Tests
python -m pytest                         # covers the deterministic risk engine
```

On first run FMS records a checkpoint and begins monitoring transactions created from that point forward.

## Configuration

- **`bank_config.yaml`** — selects the ingestion mode (`monitoring.mode`). In **API-push** mode (the default, recommended) you don't need this file at all — transactions arrive via `POST /ingest/transactions` and no database block is required. In **database-poll** mode it holds the read-only DB connection and a column mapping from your schema to FMS's normalized fields (MySQL / SQL Server / PostgreSQL / Oracle). Copy [`bank_config.example.yaml`](bank_config.example.yaml), which documents both modes. It is git-ignored so real credentials never get committed.
- **`.env`** — `GROQ_API_KEY` (case summaries), optional `GMAIL_USER` / `GMAIL_APP_PASSWORD` / `ALERT_EMAIL` (alerts), and optional `FMS_API_KEY` (API auth).

Currency-aware CTR/SAR thresholds live in `backend/services/analyzer.py` and are easy to extend for new jurisdictions.

## Security

FMS handles sensitive financial data. Use a **read-only** database user, set `FMS_API_KEY` in any shared/production deployment, keep `.env` and `bank_config.yaml` out of version control (already git-ignored), and run it on trusted infrastructure. See [SECURITY.md](SECURITY.md).

### Logging & observability

Application logs go through Python's standard `logging`, controlled entirely by environment variables — no code change to move between environments:

- **`FMS_LOG_LEVEL`** — `DEBUG` / `INFO` / `WARNING` / `ERROR` (default `INFO`).
- **`FMS_LOG_FILE`** — path to a **rotating** log file so operational history survives restarts; unset = console only. Tune with `FMS_LOG_MAX_BYTES` / `FMS_LOG_BACKUP_COUNT`. (The demo logs to console; the private `prod/` env writes to `prod/logs/fms.log`.)

Every push-ingestion call is assigned a **request id**, logged end-to-end with latency and returned as the `X-Request-ID` response header, so a single transaction can be traced through the logs. Separately, **security-relevant events** — sign-ins and failures, login rate-limiting, rejected ingestion keys, OFAC hits, and account/role changes — are recorded and surfaced under **Audit & Security → Security events** (admin only). That is distinct from the per-case compliance audit trail (who worked each case).

## Contributing

Contributions welcome — new database adapters, additional detection signals, and jurisdiction thresholds especially. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Documentation

Written so a compliance officer, examiner, or bank IT reviewer can find every answer without reading code:

| You want | Read |
|---|---|
| **Architecture** — components, data flows, trust boundaries | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| **Risk engine** — every threshold and rule, with regulatory basis and testing evidence | [MODEL.md](MODEL.md) |
| **Rule engine** — live config, tuning log, backtesting | [MODEL.md](MODEL.md) · [docs/API.md](docs/API.md#detection-rules--tuning) |
| **Deployment guide** — modes, full env-var reference, Docker, production checklist | [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) |
| **API documentation** — auth, endpoints, webhook contract + HMAC verification | [docs/API.md](docs/API.md) (live spec at `/docs`) |
| **Database schema** — every table, field groups, retention behavior | [docs/SCHEMA.md](docs/SCHEMA.md) |
| **Audit logging** — full event catalog, severities, access control | [docs/AUDIT_LOGGING.md](docs/AUDIT_LOGGING.md) |
| **RBAC design** — role matrix, dual control (maker-checker), bootstrap, LDAP/AD | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#rbac-design) |
| **OFAC integration** — SDN vs Consolidated vs PEP treatment, list refresh, 50%-rule boundary | [COMPLIANCE.md](COMPLIANCE.md#ofac-sanctions-screening) |
| **Regulatory mapping** — CTR/SAR/314(a)/retention/National Priorities, with citations | [COMPLIANCE.md](COMPLIANCE.md) |
| **Design rationale & honest limitations** — the whitepaper | [docs/WHITEPAPER.md](docs/WHITEPAPER.md) |
| **Operator manual** — sign-in, roles, working cases, reports, administration | [docs/USER_MANUAL.md](docs/USER_MANUAL.md) |
| **Security policy & data flows** | [SECURITY.md](SECURITY.md) |

## Methodology

Every threshold, scoring rule, and screening parameter is documented — with its regulatory basis and testing evidence — in [MODEL.md](MODEL.md), written to support FFIEC and interagency model-risk documentation expectations (SR 26-2, the 2026 successor to SR 11-7).

## Deliberate scope boundaries

Some capabilities are **intentionally** out of scope. Stating why matters as much as the features themselves — a tool that overclaims is a compliance risk, not a compliance aid:

- **Full entity resolution.** FMS links activity per account and matches names transparently; it does not attempt probabilistic identity graphs across accounts. Done badly, entity resolution silently merges the wrong people — a light, inspectable version (shared counterparties/identifiers) is on the roadmap; a black-box one is not.
- **The OFAC 50% ownership rule.** Requires beneficial-ownership data FMS does not hold. Institutions with ownership records can express them as alias entries in an extra screening list.
- **ML/AI detection.** Deliberate and permanent: deterministic rules are the feature. Supervisory model-risk guidance (SR 26-2) expects institutions to explain and validate their models — an alert you can't explain is an alert you can't defend. The optional LLM writes prose only and never decides anything.
- **Transmitting filings to FinCEN.** E-filing requires institution-level enrollment, and the final narrative and determination are an officer's legal responsibility. FMS prepares everything up to that line — worksheets, draft batch XML, deadline tracking — and stops there on purpose.
- **KYC/CDD onboarding.** FMS is monitoring, not identity. It consumes what your onboarding process knows (and marks exactly which filing fields need those records); owning customer identification would make it a different, worse product.
- **Horizontal scale-out.** The app store runs on SQLite out of the box and on SQL Server/PostgreSQL via `FMS_APP_DB_URL`; the poller and in-memory login throttle are single-node by design. That comfortably serves the community-institution segment FMS targets; multi-node coordination is future work, not a hidden limitation.
- **Encryption at rest / SOC 2.** Storage encryption belongs to the database engine and volume layer (see [SECURITY.md](SECURITY.md)); SOC 2 is an audit of an operating organization, not a software feature. FMS is built to be deployable *into* such an environment.

## License

Apache License 2.0 — see [LICENSE](LICENSE). Free to use, modify, and deploy (including commercially); provided as-is with no warranty; includes an explicit patent grant.
