# FMS — Fraud Monitoring System

**Open-source, real-time transaction monitoring and BSA/AML reporting for the institutions that can't afford enterprise compliance suites.**

Community banks, credit unions, money services businesses, and fintech startups carry the same Bank Secrecy Act obligations as the largest banks — Currency Transaction Reports, Suspicious Activity Reports, structuring detection — but rarely have the budget for six-figure AML platforms. FMS is a self-hostable system that watches a transaction database in real time, scores each transaction against a transparent risk engine, and produces the CTR and SAR filing lists a compliance officer needs. It is built to US FinCEN / BSA standards and runs on hardware you already have.

> **Not legal or compliance advice.** FMS is a decision-support tool. It flags activity and prepares filing lists; it does **not** file reports and does **not** replace a qualified BSA/AML officer's judgment. All filings remain the institution's responsibility. See [COMPLIANCE.md](COMPLIANCE.md).

---

## Why this matters

Financial-crime detection protects the integrity of the payment system — money laundering, terrorist financing, elder fraud, and structuring all move through the under-resourced institutions least able to detect them. Making credible, standards-aligned monitoring available as open source lowers that barrier.

## What it does

- **Real-time monitoring** — polls your core/transaction database (read-only) and analyzes every new transaction as it lands.
- **Transparent risk engine** — a fully deterministic scorer (no black box) covering:
  - Near-threshold "structuring" amounts and repeated near-misses
  - Velocity clustering across a rolling window
  - Inbound multi-source "smurfing" and same-counterparty accumulation
  - Behavioral deviation from an account's own baseline
  - New counterparty / new channel / odd-hours signals
  - Payroll/batch suppression so legitimate bulk runs don't false-positive
- **OFAC sanctions screening** — every counterparty is screened against the OFAC SDN list (refresh with `scripts/update_ofac.py`); a match forces a block-or-reject case regardless of risk score. Optional PEP list support (`data/pep.json`) for enhanced-due-diligence flags.
- **CTR assessment** — single-transaction and same-day aggregate detection against currency-aware thresholds (FinCEN USD $10,000 and local equivalents).
- **SAR assessment** — recommends a Suspicious Activity Report for structuring/smurfing (any amount) and for suspicious activity at/above the SAR threshold, with **30-day filing-deadline tracking**.
- **FinCEN filing worksheets** — `/reports/ctr?format=fincen` and `/reports/sar?format=fincen` emit Form 112 / Form 111 field structures pre-filled from transaction data, with explicit lists of what still needs KYC records and officer review.
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

## Quickstart

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

- **`bank_config.yaml`** — database connection + a column mapping from your schema to FMS's normalized fields, plus poll interval and history window. See [`bank_config.example.yaml`](bank_config.example.yaml).
- **`.env`** — `GROQ_API_KEY` (case summaries), optional `GMAIL_USER` / `GMAIL_APP_PASSWORD` / `ALERT_EMAIL` (alerts), and optional `FMS_API_KEY` (API auth).

Currency-aware CTR/SAR thresholds live in `backend/services/analyzer.py` and are easy to extend for new jurisdictions.

## Security

FMS handles sensitive financial data. Use a **read-only** database user, set `FMS_API_KEY` in any shared/production deployment, keep `.env` and `bank_config.yaml` out of version control (already git-ignored), and run it on trusted infrastructure. See [SECURITY.md](SECURITY.md).

## Contributing

Contributions welcome — new database adapters, additional detection signals, and jurisdiction thresholds especially. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Methodology

Every threshold, scoring rule, and screening parameter is documented — with its regulatory basis and testing evidence — in [MODEL.md](MODEL.md), written to support FFIEC/SR 11-7-style model documentation expectations.

## License

MIT — see [LICENSE](LICENSE).
