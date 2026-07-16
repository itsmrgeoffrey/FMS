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

## Encryption at rest (deployment concern — by design)

FMS does not implement its own storage encryption; it delegates to the layer built for it, which is how examiners expect it to be done:

- **Server databases:** run the FMS application database on SQL Server or PostgreSQL with the engine's encryption (TDE / `pgcrypto`+volume encryption) and encrypted backups.
- **SQLite deployments:** place `fms.db` (and `data/`) on an encrypted volume (BitLocker, LUKS, encrypted EBS).
- **Why not in-app crypto?** Application-level encryption of its own SQLite file would protect against exactly one threat (file theft from an unencrypted disk) while breaking backups, inspection, and portability — full-disk/database-engine encryption covers that threat properly. This is a deliberate boundary, not an omission.

## Supported data flows

By default FMS makes **no external calls with transaction data**. The complete outbound surface, all optional: email alerts (SMTP, if configured), signed webhook callbacks to the URL you configure, OFAC list downloads from treasury.gov (list data in, nothing out), and — only if you enable AI summaries — an LLM endpoint, which can be your own self-hosted model so prose generation never leaves your infrastructure. Inbound: the push-ingestion API authenticates with `X-API-Key`. Review these flows against your institution's data-handling policy before deploying.
