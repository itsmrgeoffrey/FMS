# FMS Push API — Integrator Guide

Send transactions to FMS over HTTPS and get a **risk verdict back in the same response** — no database integration required. Your systems `POST` each transaction as it happens; FMS runs the full detection engine (structuring, smurfing, velocity, deviation, OFAC sanctions screening, and CTR/SAR assessment) and returns the verdict synchronously.

This is the simplest way to integrate: **if you can make an authenticated HTTPS POST, you can use FMS.** No core-banking database access, no polling, no ETL.

> This is the deep-dive for push-mode integrators. For the full endpoint reference (cases, reports, screening, webhooks, etc.) see [`API.md`](API.md). Prefer FMS to read your core banking database directly instead of pushing? That's *DB-poll mode* — see [`DEPLOYMENT.md`](DEPLOYMENT.md) and [`ARCHITECTURE.md`](ARCHITECTURE.md).

---

## Base URL

```
https://<your-fms-host>
```

## Authentication

Every request must carry your ingestion API key in a header:

```
X-API-Key: <your key>
```

The key is configured on the server (`FMS_INGEST_API_KEY`) and shared only with the sending institution. Requests with a missing or wrong key are rejected with `401`, and every rejected attempt is recorded as a security event (a burst of them is a sign someone is probing the endpoint).

---

## Endpoint

```
POST /ingest/transactions
Content-Type: application/json
X-API-Key: <your key>
```

### Request body

| Field | Type | Required | Notes |
|---|---|:--:|---|
| `external_id` | string (≤128) | ✔ | Your unique id for this transaction. Reusing an id is treated idempotently (see below). |
| `account_id` | string (≤64) | ✔ | The account the transaction belongs to. |
| `amount` | number (> 0) | ✔ | Transaction amount. |
| `direction` | string | ✔ | `INWARD` or `OUTWARD`. |
| `timestamp` | string (ISO 8601) | — | Defaults to server time (UTC) if omitted. |
| `counterparty_account` | string (≤64) | — | Used for counterparty pattern detection. |
| `counterparty_name` | string (≤200) | — | Screened against the OFAC lists. |
| `channel` | string (≤40) | — | e.g. `wire`, `ach`, `card`, `transfer`. |
| `currency` | string (≤10) | — | Defaults to `USD`. |
| `reference` | string (≤255) | — | Free-text reference / memo. |
| `account_holder_name` | string (≤200) | — | If provided, screened against the OFAC SDN + consolidated lists. |

### Response — `200 OK`

```json
{
  "case_id": "c1a2b3…",
  "duplicate": false,
  "flagged": true,
  "risk_score": 87,
  "confidence": "HIGH",
  "fraud_type": "outward smurfing",
  "sanctions_hit": false,
  "ctr_required": false,
  "sar_recommended": true,
  "reasons": [
    "3 outward transfers just under the $10,000 CTR threshold within 24h — classic structuring.",
    "Aggregate to a single counterparty exceeds the reporting threshold."
  ]
}
```

| Field | Meaning |
|---|---|
| `case_id` | The case FMS opened (or matched, if a duplicate). |
| `duplicate` | `true` if this `external_id` was already ingested — the original verdict is returned and nothing is re-cased. |
| `flagged` | `true` if FMS opened a case for review; `false` = clean. |
| `risk_score` | Deterministic 0–100 score. |
| `confidence` | `LOW` / `MEDIUM` / `HIGH`. |
| `fraud_type` | The detected typology, if any. |
| `sanctions_hit` | `true` if an OFAC match was found. |
| `ctr_required` | `true` if the transaction triggers a Currency Transaction Report threshold. |
| `sar_recommended` | `true` if a Suspicious Activity Report is recommended. |
| `reasons` | Every rule that fired, in plain language — the full explainability trail. |

Every response also carries an **`X-Request-ID`** header so you can correlate it with your own logs.

### Behavior

- **Synchronous** — the verdict comes back in the POST response. Detect-at-the-moment, not batch.
- **Idempotent** — posting the same `external_id` again returns the original verdict (`duplicate: true`); it never opens a second case.
- **Deterministic & explainable** — the same input always yields the same score, and `reasons` states exactly which rules fired. Nothing is a black box.
- **Sanctions screening** — `account_holder_name` and `counterparty_name` are screened against the OFAC SDN / consolidated lists; a hit forces a high-confidence sanctions verdict with instructions to block or reject.

### Errors

| Status | Meaning |
|---|---|
| `401` | Missing or invalid `X-API-Key`. |
| `409` | `external_id` already ingested (duplicate). |
| `422` | Validation error — a required field is missing or a value is out of range (the response body says which). |
| `503` | Ingestion is disabled because no API key is configured on the server. |

---

## Examples

### curl

```bash
curl -X POST https://<your-fms-host>/ingest/transactions \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $FMS_INGEST_API_KEY" \
  -d '{
    "external_id": "TXN-2026-000123",
    "account_id": "ACC-778899",
    "amount": 9600,
    "direction": "OUTWARD",
    "counterparty_name": "Acme Holdings Ltd",
    "channel": "wire",
    "currency": "USD",
    "account_holder_name": "John A. Doe"
  }'
```

### Python

```python
import os, requests

resp = requests.post(
    "https://<your-fms-host>/ingest/transactions",
    headers={"X-API-Key": os.environ["FMS_INGEST_API_KEY"]},
    json={
        "external_id": "TXN-2026-000123",
        "account_id": "ACC-778899",
        "amount": 9600,
        "direction": "OUTWARD",
        "counterparty_name": "Acme Holdings Ltd",
        "channel": "wire",
        "account_holder_name": "John A. Doe",
    },
    timeout=10,
)
resp.raise_for_status()
verdict = resp.json()

if verdict["flagged"]:
    print(f"FLAGGED [{verdict['confidence']}] {verdict['fraud_type']} — risk {verdict['risk_score']}")
    for reason in verdict["reasons"]:
        print("  -", reason)
else:
    print("Clean:", verdict["case_id"])
```

### Node.js

```js
const resp = await fetch("https://<your-fms-host>/ingest/transactions", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "X-API-Key": process.env.FMS_INGEST_API_KEY,
  },
  body: JSON.stringify({
    external_id: "TXN-2026-000123",
    account_id: "ACC-778899",
    amount: 9600,
    direction: "OUTWARD",
    counterparty_name: "Acme Holdings Ltd",
    channel: "wire",
    account_holder_name: "John A. Doe",
  }),
});
const verdict = await resp.json();
console.log(verdict.flagged ? `FLAGGED ${verdict.fraud_type} (${verdict.risk_score})` : "clean");
```

---

## Interactive & machine-readable docs

FMS serves live, auto-generated OpenAPI documentation you can explore right in the browser:

| | URL |
|---|---|
| Swagger UI (try requests in-browser) | `https://<your-fms-host>/docs` |
| ReDoc (clean reference) | `https://<your-fms-host>/redoc` |
| Raw OpenAPI spec (for codegen) | `https://<your-fms-host>/openapi.json` |

The OpenAPI spec can be fed straight into a client generator (`openapi-generator`, `openapi-typescript`, …) to produce a typed client in your language.

---

## Notes for integrators

- **Send everything, let FMS decide.** Post every transaction, not just the ones you suspect — the engine needs the full stream to detect structuring, smurfing, and velocity patterns *across* transactions.
- **`external_id` is your dedupe key.** Use a stable, unique id from your system; retries are safe.
- **One transaction per request.** The endpoint is built for real-time, at-the-moment scoring, not bulk upload.
- **Minimal PII.** Names are used only for sanctions screening; omit them and screening is simply skipped. FMS stores only what you send.
- **The verdict is advisory.** FMS opens and scores the case and recommends CTR/SAR; a human still reviews and files. FMS never transmits regulatory filings itself.
