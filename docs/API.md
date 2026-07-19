# FMS API Reference

Live, always-current spec: with the backend running, open **`/docs`** (Swagger UI) or **`/openapi.json`** — FastAPI generates them from the code, so they never drift. This page is the guided tour: authentication, the endpoints grouped by job, and the webhook contract.

## Authentication

Two separate credentials for two separate callers:

| Caller | Mechanism | Notes |
|---|---|---|
| **People / the dashboard** | `Authorization: Bearer <token>` from `POST /auth/login` | HMAC-signed, expiring token (`FMS_AUTH_TOKEN_TTL_HOURS`, default 12h). Roles enforced server-side per endpoint. |
| **Machines pushing transactions** | `X-API-Key: <FMS_INGEST_API_KEY>` on `/ingest/transactions` | Rejected keys are audited (`INGEST_KEY_REJECTED`). |

Roles: **admin** / **analyst** / **viewer** — matrix in [ARCHITECTURE.md](ARCHITECTURE.md#rbac-design).

## Ingestion (API-push mode)

```
POST /ingest/transactions            X-API-Key required
```
```bash
curl -X POST http://localhost:8002/ingest/transactions \
  -H "X-API-Key: $FMS_INGEST_API_KEY" -H "Content-Type: application/json" \
  -d '{"external_id":"txn-001","account_id":"ACME-01","amount":9500,
       "direction":"OUTWARD","counterparty_name":"New Vendor LLC",
       "currency":"USD","account_holder_name":"Acme Industries"}'
```
Returns the verdict **synchronously**: risk score/level, the named signals that fired (with the actual numbers), CTR/SAR assessment, sanctions/watch-list result, and the case id if one was raised. `external_id` is idempotent — the same id never creates a duplicate case. `POST /ingest/simulate` (authenticated user, not the ingest key) exercises the same path for demos.

## Cases & investigation

| Endpoint | Role | Purpose |
|---|---|---|
| `GET /cases` | viewer+ | List/filter cases (status, confidence, dates, pagination) |
| `GET /cases/{id}` | viewer+ | Full case detail: signals, reasons, screening result, action history |
| `POST /cases/{id}/actions` | analyst+ | Dispose: `CONFIRMED_FRAUD` / `DISMISSED` / `ESCALATED` / `UNDER_REVIEW` / note — attributed to the named actor, audited as `CASE_*` |
| `GET /search?q=` | viewer+ | Global search: account, counterparty, case id, reference |
| `GET /ws` | token | WebSocket live feed — `new_case` events push to the dashboard in real time |

## Reports (CTR / SAR)

| Endpoint | Formats | Notes |
|---|---|---|
| `GET /reports/ctr` | `json` · `csv` · `fincen` · `xml` | CTR-required cases; `fincen` = Form 112 field worksheets |
| `GET /reports/sar` | `json` · `csv` · `fincen` · `xml` | SAR-recommended cases with the 30-day deadline clock; `fincen` = Form 111 worksheets |

`?format=xml` produces a **draft** batch file structured after the FinCEN E-Filing format with incomplete items marked in embedded comments — complete it and validate in FinCEN's batch validator before upload. FMS never transmits filings. Both endpoints take `date_from`/`date_to` and audit every access.

## Screening

| Endpoint | Role | Purpose |
|---|---|---|
| `POST /screening/check` | viewer+ | Batch-screen up to 5,000 names against OFAC SDN + Consolidated + PEP + extra lists; returns hits with list type, program, score |
| `POST /screening/314a` | admin | FinCEN 314(a) subject list (CSV text or names) scanned in memory against every party FMS has seen; the list is never stored; audit records counts only |

## Detection rules & tuning

| Endpoint | Role | Purpose |
|---|---|---|
| `GET /rules` | viewer+ | The live engine, fully transparent: thresholds per currency, detection windows, every scoring component, risk bands, sanctions config, National-Priorities mapping |
| `POST /rules/backtest` | admin | Replay stored history under proposed parameters — current vs. proposed flagged/SAR/CTR counts + changed examples; engine restored untouched |
| `GET /rules/changes` | viewer+ | The tuning log: every change with before/after values, actor, rationale, attached backtest evidence |

Rule changes are saved via `PUT /settings` (`rules`, `rules_rationale`, `rules_backtest`) and apply live.

## Risk assessment

| Endpoint | Role | Purpose |
|---|---|---|
| `GET /risk-assessment` | viewer+ | Latest version + version history |
| `POST /risk-assessment` | admin | Start a new draft (carries the previous version forward, fresh activity snapshot) |
| `PUT /risk-assessment/{id}` | admin | Edit a draft: category ratings, priorities checklist, conclusion |
| `POST /risk-assessment/{id}/refresh-snapshot` | admin | Regenerate the activity snapshot from current FMS data |
| `POST /risk-assessment/{id}/finalize` | admin | Freeze as the assessment of record (named finalizer; further edits 409) |

## Analytics & operations

`GET /stats` · `GET /stats/dashboard` · `GET /analytics` (KPIs) · `GET /customers` (per-account rollups) · `GET /health` (poller/bank-DB status) — viewer+. `GET /transactions` proxies read-only source-table views in poll mode.

## Administration

`/auth/*` (login, signup/bootstrap, password flows, user management — mutations queue for dual-control approval when active) · `/approvals/*` (maker-checker queue) · `/settings/*` (admin: config read/write, test-connection, test-directory, system-info) · `/audit` + `/audit/security` + `/audit/users` (admin) — full event catalog in [AUDIT_LOGGING.md](AUDIT_LOGGING.md).

## Outbound webhooks (signed callbacks)

Configure `integrations.callback_url` + `callback_secret` (Administration → API Integrations). FMS POSTs:

| Event | When |
|---|---|
| `case.flagged` | A transaction is flagged into a case |
| `case.disposition` | An analyst confirms/dismisses/escalates |

Envelope: `{"event": "...", "sent_at": <unix>, "data": {case_id, external_id, account_id, amount, currency, direction, status, risk_score, confidence, fraud_type, sanctions_hit, ctr_required, sar_recommended, reasons}}`

Every delivery carries `X-FMS-Signature`: hex HMAC-SHA256 of the **raw body** with the shared secret. Verify before trusting:

```python
import hmac, hashlib

def verify(raw_body: bytes, header_sig: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header_sig)
```

Delivery is best-effort with retries and never blocks case processing — treat the API, not the webhook, as the source of truth.
