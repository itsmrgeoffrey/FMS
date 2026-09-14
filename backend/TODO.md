Here is a comprehensive analysis of the FMS codebase with actionable improvement areas:
FMS Codebase Improvement Analysis
1. Architecture — God Modules
backend/services/analyzer.py (991 lines) is the single biggest structural problem. It contains 6 distinct concerns in one file:
- LLM client + summary generation
- CTR/SAR threshold config + rule overrides
- Regulatory assessment logic
- Behavioral profiling + risk scoring
- Reason generation + fraud type classification
- Summary assembly + the main analyze() function (138 lines alone)
frontend/app/settings/page.tsx (1161 lines) contains 7 inline components (Field, Section, MyAccountSection, UsersSection, ApprovalsSection, ComingSoon, SettingsPage). It also blanket-disables eslint-disable @typescript-eslint/no-explicit-any.
backend/routers/ingest.py:77-186 — run_ingest() is a 110-line function that acts as an entire service (transaction storage, analysis, case creation, notifications, audit logging) embedded in a router.
2. Code Duplication
Pattern	Locations
FraudCase(...) constructor (~20 fields)	poller.py:114-138, ingest.py:140-151
Sanctions result handling (if/elif chains)	analyzer.py:847-885, ingest.py:118-138
Broadcast + email notification	poller.py:158-181, ingest.py:169-184
count() helper (4 separate definitions)	stats.py:19, stats.py:50, insights.py:102, risk.py:74
fmtDate/fmt/fmtMoney (3-4 impls each)	CasesTable.tsx, AuditTrail.tsx, alerts/page.tsx, cases/[id]/page.tsx
Error message parsing (String(e).replace(...))	settings/page.tsx:90,165,363,554
3. Security Issues
Severity	Issue
High	WebSocket endpoint only does HMAC verify, no DB user lookup — disabled users can still connect
High	Token in URL query string (visible in logs, browser history)
High	No token revocation mechanism
Medium	Rate limiter is in-memory defaultdict(list) with no eviction — unbounded memory growth
Medium	Setup token comparison uses != not hmac.compare_digest (timing attack)
Medium	resolve_actor doesn't sanitize user input before audit log insertion
Low	CSRF protection absent (mitigated by token-in-header pattern)
4. State Mutation & Configuration
- Module-level globals mutated at import time: analyzer.py:991 calls apply_rule_overrides() at import, making it non-reentrant and hard to test
- Hardcoded CORS origins (not configurable): main.py:93
- Hardcoded SMTP server: services/emailer.py:53,152 — non-Gmail deployments require code changes
- Hardcoded WebSocket port: useWebSocket.ts:18
- App auto-writes secrets to disk if auth_secret not set: config.py:73-78
- config.py uses both os.getenv() and pydantic_settings — two competing config paths
- bank_config loaded at module level as mutable dict: config.py:104
5. Type Safety
Backend:
- datetime.utcnow() used ~30 times (deprecated since Python 3.12) — use datetime.now(timezone.utc)
- Most router handlers lack return type annotations
- Record<string, any> in sanctions.py, callbacks.py, poller.py
- SessionLocal() created directly in routers bypassing DI (ingest.py:152, audit.py:43, settings.py:335)
Frontend:
- JSON.parse(raw) as AuthUser with no runtime validation (api.ts:18)
- Record<string, any> with eslint-disable (api.ts:111)
- 9+ uses of any in settings/page.tsx
- LiveFeed.tsx duplicates a local Alert interface instead of reusing WsNewCase
- FraudCaseListItem.status: string vs proper union type in FraudCase
6. Performance
Issue
WebSocket reconnects every render — inline callback without useCallback
Zero usage of React.memo, useMemo, useCallback
No server components — every page is "use client"
Chart calculations run on every render without useMemo
setInterval polling creates new closure each time
Missing index on FraudCase.timestamp — used in all range queries
Missing indexes on risk_score, confidence
No connection pool tuning
7. Testing Gaps
Area	Status
Risk engine tests	B
Auth tests	B+
Compliance tests	B+
Dual control tests	A-
Sanctions tests	B
Router integration tests	None
Middleware tests	None
Frontend tests	None
8. Infrastructure
CI Pipeline (ci.yml):
- No pip/node caching — full install every run
- No linting step (no ruff, mypy, eslint)
- No test coverage reporting
- No security scanning (pip-audit, safety)
- Triggers on every push to every branch (no branch filter)
- No matrix testing (Python 3.12, Windows)
Docker:
- Runs as root — no USER directive
- No multi-stage build (larger image than needed)
- No HEALTHCHECK instruction
- .env mounted read-write (container can modify host file)
- No resource limits (mem_limit, cpus)
- No log rotation configured
- No network isolation between services
Dependencies:
- pytest mixed into production requirements.txt
- Unused DB drivers (asyncpg, oracledb) installed for all deployments
- No hash pinning — supply-chain attack vector
- No requirements-dev.txt separation
Database Migrations:
- SQLite-only raw SQL migrations — no Alembic
- No version tracking or downgrade support
- No multi-dialect migration strategy
9. Separation of Concerns
File
routers/ingest.py:77-186
routers/insights.py:405-500
routers/insights.py:179-218
routers/reports.py:92-253
routers/settings.py:298-436
services/poller.py:24-38
services/sanctions.py:85-93
10. Missing Error Handling
- No global exception handler in main.py — unhandled errors return FastAPI's default HTML 500
- Bare except Exception in auth.py:44,80 silently swallows errors with no logging
- Error responses return 200 with error key instead of proper HTTP status codes (insights.py:159,239)
- Audit log failures silently swallowed (audit.py:42-53) — critical for a compliance tool
- Zero error boundaries in frontend — component crash = white screen
- No loading.tsx or error.tsx in any Next.js route directory
11. Accessibility
- <select> elements have no <label> or aria-label (CasesTable.tsx:46-59)
- <nav> has no aria-label (AppShell.tsx:95)
- No ARIA live regions for real-time alerts (LiveFeed.tsx)
- No skip-to-content link
- Tables lack <caption> elements
- No keyboard navigation testing
Priority Action Items
Priority	Action
1	Split analyzer.py into focused modules
2	Split settings/page.tsx into separate components
3	Extract duplicated FraudCase construction, notifications, sanctions handling
4	Add global exception handler + proper HTTP error codes
5	Fix WebSocket reconnect bug (useCallback in LiveFeed)
6	Add USER appuser + multi-stage build to Dockerfile
7	Separate requirements-dev.txt, add linting to CI
8	Replace datetime.utcnow() with datetime.now(timezone.utc)
9	Add missing DB indexes (timestamp, risk_score)
10	Add React error boundaries + loading.tsx/error.tsx
11	Move CORS origins, SMTP server, WebSocket port to config
12	Add Alembic for proper migration management
13	Add router integration tests
14	Implement token revocation / WS user lookup
15	Add resource limits, log rotation, network isolation to Docker Compose