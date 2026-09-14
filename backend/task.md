# FMS Backend Task List

Tasks derived from codebase analysis, organized by category with metadata. Check off tasks as they're completed.

---

## Architecture & Code Quality

### Task 1: Split analyzer.py into focused modules

| Metadata | Value |
|----------|-------|
| **Priority** | 1 (Critical) |
| **Estimated Time** | 8-12 hours |
| **Dependencies** | None |
| **Status** | Pending |
| **Category** | Architecture — God Modules |

**Current State:** `backend/services/analyzer.py` (991 lines) is the single biggest structural problem. It contains 6 distinct concerns in one file:

- LLM client + summary generation
- CTR/SAR threshold config + rule overrides
- Regulatory assessment logic
- Behavioral profiling + risk scoring
- Reason generation + fraud type classification
- Summary assembly + the main analyze() function (138 lines alone)

**Action:** Decompose into focused modules (e.g., `risk_engine.py`, `llm_client.py`, `regulatory.py`, `profiler.py`, `reason_generator.py`, `summary_builder.py`).

- [ ] Create new module structure under `backend/services/`
- [ ] Extract LLM client and summary generation
- [ ] Extract CTR/SAR threshold config and rule overrides
- [ ] Extract regulatory assessment logic
- [ ] Extract behavioral profiling and risk scoring
- [ ] Extract reason generation and fraud type classification
- [ ] Extract summary assembly
- [ ] Refactor `analyze()` function to compose new modules
- [ ] Update imports in all dependent files
- [ ] Run tests to verify no regressions

---

### Task 2: Split settings/page.tsx into separate components

| Metadata | Value |
|----------|-------|
| **Priority** | 2 (High) |
| **Estimated Time** | 4-6 hours |
| **Dependencies** | None |
| **Status** | Pending |
| **Category** | Architecture — God Modules |

**Current State:** `frontend/app/settings/page.tsx` (1161 lines) contains 7 inline components (Field, Section, MyAccountSection, UsersSection, ApprovalsSection, ComingSoon, SettingsPage). It also blanket-disables `eslint-disable @typescript-eslint/no-explicit-any`.

**Action:** Extract each component into its own file under `frontend/components/settings/`.

- [ ] Create `frontend/components/settings/` directory
- [ ] Extract `Field` component
- [ ] Extract `Section` component  
- [ ] Extract `MyAccountSection` component
- [ ] Extract `UsersSection` component
- [ ] Extract `ApprovalsSection` component
- [ ] Extract `ComingSoon` component
- [ ] Refactor `SettingsPage` to use extracted components
- [ ] Remove `eslint-disable` and fix TypeScript issues
- [ ] Update imports in settings page

---

## Code Duplication & Refactoring

### Task 3: Extract duplicated FraudCase construction, notifications, sanctions handling

| Metadata | Value |
|----------|-------|
| **Priority** | 3 (High) |
| **Estimated Time** | 6-8 hours |
| **Dependencies** | Task 1 (analyzer.py split) |
| **Status** | Pending |
| **Category** | Code Duplication |

**Current State:** Multiple patterns of code duplication:

| Pattern | Locations |
|---------|-----------|
| `FraudCase(...)` constructor (~20 fields) | `poller.py:114-138`, `ingest.py:140-151` |
| Sanctions result handling (if/elif chains) | `analyzer.py:847-885`, `ingest.py:118-138` |
| Broadcast + email notification | `poller.py:158-181`, `ingest.py:169-184` |
| `count()` helper (4 separate definitions) | `stats.py:19`, `stats.py:50`, `insights.py:102`, `risk.py:74` |

**Action:** Create shared utility functions and factories.

- [ ] Create `FraudCaseFactory` class or function
- [ ] Create shared `handle_sanctions_result()` function
- [ ] Create shared `send_notifications()` function
- [ ] Create single `count()` utility function
- [ ] Update all locations to use shared functions
- [ ] Remove duplicated code
- [ ] Run tests to verify no regressions

---

## Error Handling & Security

### Task 4: Add global exception handler + proper HTTP error codes

| Metadata | Value |
|----------|-------|
| **Priority** | 4 (High) |
| **Estimated Time** | 4-6 hours |
| **Dependencies** | None |
| **Status** | Pending |
| **Category** | Missing Error Handling |

**Current State:**

- No global exception handler in `main.py` — unhandled errors return FastAPI's default HTML 500
- Bare `except Exception` in `auth.py:44,80` silently swallows errors with no logging
- Error responses return 200 with error key instead of proper HTTP status codes (`insights.py:159,239`)
- Audit log failures silently swallowed (`audit.py:42-53`) — critical for a compliance tool

**Action:** Implement proper error handling throughout the application.

- [ ] Add global exception handler in `main.py`
- [ ] Create custom exception classes (e.g., `ValidationError`, `NotFoundError`, `AuthenticationError`)
- [ ] Replace bare `except Exception` with specific exception handling
- [ ] Add proper HTTP status codes (400, 401, 403, 404, 500)
- [ ] Add logging for all exceptions
- [ ] Fix audit log error handling to propagate or alert
- [ ] Update frontend to handle new error responses

---

### Task 14: Implement token revocation / WS user lookup

| Metadata | Value |
|----------|-------|
| **Priority** | 14 (Low) |
| **Estimated Time** | 8-10 hours |
| **Dependencies** | Task 4 (error handling) |
| **Status** | Pending |
| **Category** | Security Issues |

**Current State:**

- High: WebSocket endpoint only does HMAC verify, no DB user lookup — disabled users can still connect
- High: Token in URL query string (visible in logs, browser history)
- High: No token revocation mechanism
- Medium: Rate limiter is in-memory `defaultdict(list)` with no eviction — unbounded memory growth
- Medium: Setup token comparison uses `!=` not `hmac.compare_digest` (timing attack)
- Medium: `resolve_actor` doesn't sanitize user input before audit log insertion

**Action:** Implement proper token management and security.

- [ ] Implement token revocation (blacklist or short-lived tokens with refresh)
- [ ] Add DB user lookup for WebSocket connections
- [ ] Move token from URL to header
- [ ] Add rate limiter eviction strategy
- [ ] Use `hmac.compare_digest` for token comparison
- [ ] Sanitize user input in audit logging

---

## Performance & Frontend

### Task 5: Fix WebSocket reconnect bug (useCallback in LiveFeed)

| Metadata | Value |
|----------|-------|
| **Priority** | 5 (Medium) |
| **Estimated Time** | 2-3 hours |
| **Dependencies** | None |
| **Status** | Pending |
| **Category** | Performance |

**Current State:** WebSocket reconnects every render — inline callback without `useCallback`.

**Action:** Optimize WebSocket connection handling.

- [ ] Wrap WebSocket callback in `useCallback`
- [ ] Add proper cleanup on unmount
- [ ] Implement exponential backoff for reconnection
- [ ] Add connection state management
- [ ] Test WebSocket stability under network interruptions

---

### Task 9: Add missing DB indexes (timestamp, risk_score)

| Metadata | Value |
|----------|-------|
| **Priority** | 9 (Medium) |
| **Estimated Time** | 2-3 hours |
| **Dependencies** | None |
| **Status** | Pending |
| **Category** | Performance |

**Current State:**

- Missing index on `FraudCase.timestamp` — used in all range queries
- Missing indexes on `risk_score`, `confidence`

**Action:** Add database indexes for query performance.

- [ ] Add index on `FraudCase.timestamp`
- [ ] Add index on `FraudCase.risk_score`
- [ ] Add index on `FraudCase.confidence`
- [ ] Consider composite indexes for common query patterns
- [ ] Test query performance improvement
- [ ] Document index strategy

---

### Task 10: Add React error boundaries + loading.tsx/error.tsx

| Metadata | Value |
|----------|-------|
| **Priority** | 10 (Medium) |
| **Estimated Time** | 4-6 hours |
| **Dependencies** | Task 2 (settings component split) |
| **Status** | Pending |
| **Category** | Missing Error Handling |

**Current State:**

- Zero error boundaries in frontend — component crash = white screen
- No `loading.tsx` or `error.tsx` in any Next.js route directory

**Action:** Implement React error handling patterns.

- [ ] Create `ErrorBoundary` component
- [ ] Add error boundaries to key pages
- [ ] Create `loading.tsx` for each route
- [ ] Create `error.tsx` for each route
- [ ] Add proper error reporting
- [ ] Test error recovery flows

---

## Type Safety & Configuration

### Task 8: Replace datetime.utcnow() with datetime.now(timezone.utc)

| Metadata | Value |
|----------|-------|
| **Priority** | 8 (Medium) |
| **Estimated Time** | 2-3 hours |
| **Dependencies** | None |
| **Status** | Pending |
| **Category** | Type Safety |

**Current State:** `datetime.utcnow()` used ~30 times (deprecated since Python 3.12).

**Action:** Replace all deprecated datetime calls.

- [ ] Find all `datetime.utcnow()` occurrences
- [ ] Replace with `datetime.now(timezone.utc)`
- [ ] Update imports to include `timezone`
- [ ] Run tests to verify timezone handling
- [ ] Add linting rule to prevent future usage

---

### Task 11: Move CORS origins, SMTP server, WebSocket port to config

| Metadata | Value |
|----------|-------|
| **Priority** | 11 (Medium) |
| **Estimated Time** | 3-4 hours |
| **Dependencies** | None |
| **Status** | Pending |
| **Category** | State Mutation & Configuration |

**Current State:**

- Hardcoded CORS origins (not configurable): `main.py:93`
- Hardcoded SMTP server: `services/emailer.py:53,152` — non-Gmail deployments require code changes
- Hardcoded WebSocket port: `useWebSocket.ts:18`
- App auto-writes secrets to disk if auth_secret not set: `config.py:73-78`
- `config.py` uses both `os.getenv()` and `pydantic_settings` — two competing config paths

**Action:** Centralize all configuration.

- [ ] Move CORS origins to environment variable
- [ ] Move SMTP server to configuration
- [ ] Move WebSocket port to configuration
- [ ] Remove auto-write secrets behavior
- [ ] Standardize on `pydantic_settings` for all config
- [ ] Update documentation with new config options

---

## Infrastructure & DevOps

### Task 6: Add USER appuser + multi-stage build to Dockerfile

| Metadata | Value |
|----------|-------|
| **Priority** | 6 (Medium) |
| **Estimated Time** | 3-4 hours |
| **Dependencies** | None |
| **Status** | Pending |
| **Category** | Infrastructure |

**Current State:** Docker runs as root — no `USER` directive. No multi-stage build (larger image than needed).

**Action:** Improve Docker security and efficiency.

- [ ] Create non-root `appuser` in Dockerfile
- [ ] Add `USER appuser` directive
- [ ] Implement multi-stage build to reduce image size
- [ ] Add `.dockerignore` entries for unnecessary files
- [ ] Test container runs correctly as non-root
- [ ] Verify file permissions are correct

---

### Task 7: Separate requirements-dev.txt, add linting to CI

| Metadata | Value |
|----------|-------|
| **Priority** | 7 (Medium) |
| **Estimated Time** | 4-5 hours |
| **Dependencies** | None |
| **Status** | Pending |
| **Category** | Infrastructure |

**Current State:**

- pytest mixed into production `requirements.txt`
- Unused DB drivers (asyncpg, oracledb) installed for all deployments
- No hash pinning — supply-chain attack vector
- No `requirements-dev.txt` separation
- CI has no linting step (no ruff, mypy, eslint)

**Action:** Separate dependencies and add linting.

- [ ] Create `requirements-dev.txt` with test/lint dependencies
- [ ] Remove pytest from production `requirements.txt`
- [ ] Add optional dependency groups for DB drivers
- [ ] Add `ruff` for Python linting
- [ ] Add `mypy` for type checking
- [ ] Add `eslint` for TypeScript linting
- [ ] Update CI pipeline to run linting
- [ ] Add pre-commit hooks for linting

---

### Task 12: Add Alembic for proper migration management

| Metadata | Value |
|----------|-------|
| **Priority** | 12 (Low) |
| **Estimated Time** | 6-8 hours |
| **Dependencies** | Task 9 (DB indexes) |
| **Status** | Pending |
| **Category** | Infrastructure |

**Current State:**

- SQLite-only raw SQL migrations — no Alembic
- No version tracking or downgrade support
- No multi-dialect migration strategy

**Action:** Implement proper database migrations.

- [ ] Install and configure Alembic
- [ ] Create initial migration from current schema
- [ ] Add migration scripts for all dialects (SQLite, PostgreSQL, MySQL, MSSQL)
- [ ] Test migration up/downgrade paths
- [ ] Update deployment scripts to use Alembic
- [ ] Document migration workflow

---

### Task 15: Add resource limits, log rotation, network isolation to Docker Compose

| Metadata | Value |
|----------|-------|
| **Priority** | 15 (Low) |
| **Estimated Time** | 4-5 hours |
| **Dependencies** | Task 6 (Docker USER) |
| **Status** | Pending |
| **Category** | Infrastructure |

**Current State:**

- No resource limits (`mem_limit`, `cpus`)
- No log rotation configured
- No network isolation between services
- `.env` mounted read-write (container can modify host file)

**Action:** Harden Docker Compose configuration.

- [ ] Add memory limits to all services
- [ ] Add CPU limits to all services
- [ ] Configure log rotation
- [ ] Create dedicated networks for service isolation
- [ ] Mount `.env` as read-only
- [ ] Add health checks for all services
- [ ] Document resource requirements

---

## Testing & Quality Assurance

### Task 13: Add router integration tests

| Metadata | Value |
|----------|-------|
| **Priority** | 13 (Low) |
| **Estimated Time** | 10-12 hours |
| **Dependencies** | Task 4 (error handling), Task 3 (code duplication) |
| **Status** | Pending |
| **Category** | Testing Gaps |

**Current State:** Router integration tests: None

**Action:** Add comprehensive router tests.

- [ ] Set up test fixtures for database
- [ ] Add tests for `auth_routes.py`
- [ ] Add tests for `cases.py`
- [ ] Add tests for `transactions.py`
- [ ] Add tests for `ingest.py`
- [ ] Add tests for `approvals.py`
- [ ] Add tests for `audit.py`
- [ ] Add tests for `settings.py`
- [ ] Add tests for `stats.py`, `insights.py`, `risk.py`
- [ ] Achieve >80% coverage on routers

---

## Summary Dashboard

| Category | Total Tasks | Completed | In Progress | Remaining |
|----------|-------------|-----------|-------------|-----------|
| Architecture & Code Quality | 2 | 0 | 0 | 2 |
| Code Duplication & Refactoring | 1 | 0 | 0 | 1 |
| Error Handling & Security | 2 | 0 | 0 | 2 |
| Performance & Frontend | 3 | 0 | 0 | 3 |
| Type Safety & Configuration | 2 | 0 | 0 | 2 |
| Infrastructure & DevOps | 4 | 0 | 0 | 4 |
| Testing & Quality Assurance | 1 | 0 | 0 | 1 |
| **Total** | **15** | **0** | **0** | **15** |

## Usage Instructions

1. **Work in Priority Order:** Start with Task 1 (Critical) and proceed sequentially
2. **Update Status:** Change `[ ]` to `[x]` when task is completed
3. **Track Dependencies:** Ensure prerequisite tasks are completed before starting dependent tasks
4. **Add Notes:** Include blockers, decisions, or important notes in comments below each task
5. **Update Metadata:** Adjust estimated time based on actual effort

## Priority Legend

- **Critical (1):** Must be done first, blocks other work
- **High (2-4):** Important for stability and maintainability
- **Medium (5-11):** Improves performance, security, or developer experience
- **Low (12-15):** Nice to have, can be done later