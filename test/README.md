# FMS — Demo / Test environment

A self-contained, **safe-to-run demo**: a pre-seeded SQLite database with sample
cases and three ready-made accounts. No real credentials, no external calls, no
bank database required (runs in API-push mode). This is the environment used for
screenshots, evaluation, and trying the product.

## Run it

**Backend** (from the project root):
```bash
./test/run.sh          # macOS/Linux
.\test\run.ps1         # Windows PowerShell
```

**Frontend** (second terminal):
```bash
cd frontend && npm install && npm run dev
```

Open **http://localhost:3000**.

## Demo accounts

| Role | Email | Password |
|---|---|---|
| Admin | `admin@fms.demo` | `DemoAdmin!2026` |
| Analyst | `analyst@fms.demo` | `DemoAnalyst!2026` |
| Viewer | `viewer@fms.demo` | `DemoViewer!2026` |

Sign in as each to see the role differences (admin sees Administration; viewer is read-only).

## Push a transaction (API mode)

The demo runs in API-push mode. Send a transaction and get the risk verdict back:
```bash
curl -X POST http://localhost:8002/ingest/transactions \
  -H "X-API-Key: demo-ingest-key" -H "Content-Type: application/json" \
  -d '{"external_id":"demo-1","account_id":"ACME-01","amount":9500,
       "direction":"OUTWARD","counterparty_name":"New Vendor LLC","currency":"USD"}'
```

## Notes

- Everything here is intentionally committed and contains **no real secrets**. The
  `FMS_AUTH_SECRET` and ingest key are fixed demo values — never reuse them.
- To reset the demo data: `FMS_DB_PATH=test/fms_demo.db python scripts/seed_demo.py`.
- For a real deployment, use the private `prod/` environment instead (not committed).
