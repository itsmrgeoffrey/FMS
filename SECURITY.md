# Security Policy

FMS processes sensitive financial data. Please treat it accordingly.

## Reporting a vulnerability

Do **not** open a public issue for security vulnerabilities. Report them privately to the maintainer at **iloanitochukwu@gmail.com** with details and reproduction steps. You'll get an acknowledgement and a coordinated fix/disclosure timeline.

## Deployment guidance

- **Read-only database access.** Connect FMS to your banking database with a dedicated read-only user. FMS never writes to the source database.
- **Enable API auth.** Set `FMS_API_KEY` for any shared or production deployment so `/cases` and `/reports` require the `X-API-Key` header. It is intentionally off by default only for local development.
- **Keep secrets out of git.** `.env`, `bank_config.yaml`, and `fms.db` are git-ignored. Never commit credentials or real transaction data.
- **Protect the case store.** `fms.db` (SQLite) contains flagged transactions and analyst notes — restrict file permissions and back it up securely.
- **Run on trusted infrastructure.** Terminate TLS in front of the API, restrict network access, and do not expose the backend directly to the public internet without an authenticating proxy.

## Supported data flows

FMS reads from your transaction database, stores case data locally, sends optional email alerts (SMTP), and calls a third-party LLM API for case summaries. Review these flows against your institution's data-handling policy before deploying.
