# FMS — User Manual

**Fraud Monitoring System · Transaction monitoring and BSA/AML compliance**

This manual is for the people who operate FMS day to day — compliance officers, analysts, and the administrator who sets it up. For developer/API documentation, see the [README](../README.md); for the detection methodology, see [MODEL.md](../MODEL.md); for regulatory alignment, see [COMPLIANCE.md](../COMPLIANCE.md).

---

## 1. What FMS does

FMS watches your institution's transaction database in near-real time and:

1. **Analyzes every new transaction** with a deterministic rule engine (structuring, smurfing, velocity, behavioral deviation, and more). No black box: every flag comes with plain-English reasons.
2. **Screens every counterparty** against the US Treasury OFAC sanctions (SDN) list.
3. **Identifies regulatory obligations** — Currency Transaction Reports (CTR) and Suspicious Activity Reports (SAR) — with filing worksheets and deadline tracking.
4. **Raises alerts** so your team can act while it matters (e.g., place a hold before funds are swept), and records every decision in an audit trail.

FMS **reads** your banking database and never writes to it. It prepares filings but does not transmit anything to any regulator — a human officer always decides.

By default FMS uses **no AI**: all analysis is deterministic and no transaction data leaves your server. An optional AI prose summary can be enabled by an administrator (see §8.6).

---

## 2. Getting started

### 2.1 Requirements
- The FMS backend and frontend running (see §2.2), with network access to your transaction database (MySQL or SQL Server).
- A modern browser (Chrome, Edge, Firefox).

### 2.2 Starting FMS

**Option A — Docker (recommended for deployments):**
```bash
cp .env.example .env
cp bank_config.example.yaml bank_config.yaml
docker compose up -d
# open http://localhost:3000
```

**Option B — manual (development / local):**
```bash
# Backend (from the project root)
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8002

# Frontend (in a second terminal)
cd frontend && npm run dev
# open http://localhost:3000
```

### 2.3 First sign-in
1. Open `http://localhost:3000`. You'll land on the sign-in page.
2. Click **Create account**. Enter your full name, **email**, and a password (8+ characters).
3. **The first account created automatically becomes the administrator.** Everyone who signs up after that starts as an analyst.

> ⚠️ Type your password rather than pasting it — a pasted trailing space is the single most common cause of "Invalid email or password."

---

## 3. Roles and access

| Capability | Admin | Analyst | Viewer |
|---|:---:|:---:|:---:|
| View dashboards, cases, reports | ✅ | ✅ | ✅ |
| Act on cases (review / confirm / dismiss / escalate) | ✅ | ✅ | ❌ |
| Use the transaction simulator | ✅ | ✅ | ❌ |
| Administration (configuration, users) | ✅ | ❌ | ❌ |

Access is enforced by the server, not just hidden in the menu. Admins assign roles in **Administration → Users**. You cannot demote or disable your own account.

---

## 4. The interface

The sidebar is grouped into sections (click a bold header to collapse it):

### OVERVIEW
- **Dashboard** — the landing page. Open cases, flagged today, sanctions hits, open SARs with the soonest 30-day deadline, CTR count, amount under investigation, a 14-day activity chart, fraud-type breakdown, risk distribution, and the highest-risk open cases ("Needs attention"). Auto-refreshes every 30 seconds.
- **Analytics** — KPIs (value flagged, transactions processed, alerts today, open cases, false-positive rate among reviewed alerts) plus distribution charts. The false-positive rate shows "—" until alerts have actually been confirmed or dismissed.

### OPERATIONS
- **Alerts** — the work queue: open cases ordered by risk, with OFAC/SAR/CTR badges. Start here each day.
- **Transactions** — every transaction the engine analyzed, filterable All / Flagged / Clean.
- **Customers** — per-account rollup: volume, flagged counts, peak risk, sanctions/SAR flags.
- **Cases** — all cases with status and confidence filters, and the case detail view (§5).

### DETECTION
- **Rule Engine** — a read-only view of every threshold and scoring rule the engine uses (CTR thresholds per currency, structuring band, detection windows, scoring components, risk levels, sanctions matching). What you see here is exactly what runs.

### COMPLIANCE
- **Reports (SAR/STR)** — the SAR and CTR filing lists with deadlines, exportable as CSV (§6).
- **Audit Trail** — who did what, when, from which IP (§7).

### SYSTEM
- **Administration** — configuration, users, account (§8). Admins only.

### TOOLS
- **Simulate (Demo)** — a mock mobile-banking app that writes test transactions into the monitored database so you can watch FMS detect them end to end (§9).

---

## 5. Working a case

Open a case from **Alerts**, **Cases**, or the Dashboard's "Needs attention" list.

**A case shows:**
- **Transaction details** — account, amount, direction, counterparty, channel, time.
- **Regulatory panels** (when applicable):
  - 🔴 **OFAC MATCH** — the counterparty matched the sanctions list. This is a block/reject obligation, not a suggestion. Verify the match (name screening can false-positive), then escalate to your BSA officer immediately.
  - 🟡 **SAR RECOMMENDED** — suspicious activity meeting the SAR reporting bar, with the reason.
  - 🔵 **CTR REQUIRED** — a Currency Transaction Report obligation (this alone does not mean fraud).
- **Fraud Risk Analysis** — the 0–100 risk score, the fraud typology (e.g., "multi-source smurfing", "invoice fraud"), and plain-English reasons for every signal that fired.
- **Take Action** — with an optional note:
  - **Mark Under Review** — you're investigating.
  - **Confirm Fraud** — closes the case as confirmed.
  - **Dismiss** — closes as a false positive (this feeds the false-positive KPI).
  - **Escalate** — hands it up for senior review.
- **Audit Trail** — every action on this case, by whom, when.

Actions are attributed to your signed-in identity and recorded permanently. Viewers see cases read-only.

---

## 6. Regulatory reports

**Reports (SAR/STR)** has two tabs:

- **SAR / STR** — every case where a Suspicious Activity Report is recommended, with the detection date, the **30-day filing deadline**, and days remaining (red when ≤ 7 days).
- **CTR** — every transaction meeting the currency-transaction-reporting threshold, with the trigger (single transaction or same-day aggregate).

**Export CSV** downloads the current list. For FinCEN-shaped worksheets (Form 111 / Form 112 field structure, pre-filled from transaction data), call the API with `?format=fincen` — fields FMS cannot know (KYC identifiers) are explicitly listed for manual completion.

> FMS prepares filings; it does not file. Filing with FinCEN remains your institution's responsibility.

---

## 7. Audit Trail

Every consequential action is recorded: sign-ins (including **failed** attempts), case actions, settings changes (with old → new values for database fields), password resets, role changes, and user enable/disable. Each entry shows the user, the action, the target, detail, IP address, and timestamp. Use the Last 50/100/200 selector and Refresh.

---

## 8. Administration (admins only)

### 8.1 System Settings → Bank Database
Connection status (Connected/Disconnected, last checked), type (MySQL/SQL Server), host, port, database, credentials or Windows Authentication, TLS options, and a **Test Connection** button. Use a **read-only** database user — FMS never needs write access.
> Database and table-mapping changes are saved immediately but need a **backend restart** to take effect (the badge says "Pending Restart").

### 8.2 System Settings → Table Mappings
Map your table and column names onto the fields FMS understands (id, account, amount, timestamp, counterparty, channel, currency, reference), separately for inward and outward tables.

### 8.3 System Settings → Monitoring
Poll interval (how often FMS checks for new transactions) and the history window used as each account's behavioral baseline. Applied live.

### 8.4 System Settings → Institution
Your institution's name, EIN, regulator, and address — used to pre-fill the FinCEN worksheet filing-institution section. Applied live.

### 8.5 System Settings → Email Alerts
Gmail address + app password + recipient for fraud-alert emails and password-reset emails. If not configured, FMS still works — password resets fall back to showing a temporary password on screen.

### 8.6 System Settings → AI Summaries
**Off by default.** When off, case summaries are written deterministically and no transaction data leaves your server. When enabled, an LLM writes the prose summary only — it never influences detection. Use a self-hosted endpoint URL to keep data on your infrastructure.

### 8.7 System Settings → Security
The optional machine API key protecting the ingestion endpoint. Below the settings you'll find the System Information panel (version, environment, database status, server time) and the recent configuration-change log.

### 8.8 My Account
Change your own password (all roles have this — non-admins reach it via the **Account** link at the bottom of the sidebar).

### 8.9 Users
- **Assign roles** — Admin / Analyst / Viewer dropdown per user.
- **Reset password** — emails a temporary password if email is configured; otherwise shows it once on screen for you to hand over securely. The user should change it after signing in.
- **Enable/Disable** accounts.

**Forgot password?** Users can request a reset from the sign-in page (requires email to be configured), or ask an admin to reset it here.

### 8.10 Directory (SSO — LDAP / Active Directory)
Optionally let staff sign in with their existing Active Directory / LDAP credentials instead of separate FMS passwords. Configure the server URI (`ldaps://…`), the bind template (how a username becomes a bind DN, e.g. `{username}@yourbank.com`), the base DN and user-search filter for group lookup, and a **group → role map** (e.g. `FMS-Admins → admin`, `FMS-Analysts → analyst`) with a default role for everyone else. Use **Test Directory Connection** to confirm reachability before enabling.

When enabled: a user signs in with their AD credentials, FMS verifies them against the directory, maps their groups to an FMS role, and creates their account automatically on first login — no directory password is ever stored in FMS. **Built-in local accounts keep working**, so an unreachable or misconfigured directory can never lock you out; the local admin can always sign in.

### 8.11 Roles / Permissions / API Integrations
Shown locked ("Coming soon") — the built-in three-role model is active today; granular permissions and integration management are planned.

---

## 9. Testing with the simulator

**Tools → Simulate (Demo)** opens a mock banking app that writes transactions into the monitored database — the same path a real core would feed.

Try these and watch the Dashboard/Alerts react (within one poll interval, ~15–30s):

| To trigger… | Send… |
|---|---|
| High-value + CTR | A single transfer over $10,000 |
| Structuring flag | An amount just under $10,000 (e.g., $9,500) |
| Multi-source smurfing | 3–4 inward transfers from *different* senders to one account, each a few thousand dollars, within minutes |
| Invoice-fraud pattern | A large outward transfer to a counterparty the account has never paid |

---

## 10. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| "Invalid email or password" but you're sure | A trailing space from copy-paste. Use the eye icon 👁 to inspect exactly what's in the field, and type it manually. |
| "Too many login attempts" (429) | Brute-force protection: 10 failed attempts per 5 minutes per IP. Wait a few minutes. |
| Changed DB settings but nothing happened | Database/table-mapping changes need a backend restart ("Pending Restart" badge). |
| New transactions aren't appearing | Check Administration → Bank Database → Test Connection; check the poll interval; confirm the poller is running via the System Information panel. FMS starts monitoring from the moment it first sees a table — pre-existing rows are not back-processed. |
| Password-reset email never arrives | Email isn't configured (§8.5). Admin reset will show the temporary password on screen instead. |
| A sanctions hit looks wrong | Name screening can false-positive (similar names). The case shows the matched list entry and score — verify before acting, and document the outcome via case actions. |
| Locked out entirely | Any admin can reset your password in Administration → Users. If the *only* admin is locked out, access must be restored at the database level — contact your technical operator. |

---

## 11. Data handling summary

- **Your banking database:** read-only. FMS never writes to it.
- **FMS's own data** (cases, users, audit log): stored in FMS's application database, separate from the banking database.
- **Passwords:** stored as PBKDF2 hashes, never plain text, never displayed.
- **Transaction data:** stays on your server unless an admin explicitly enables AI summaries with a third-party key (§8.6).
- **OFAC list:** downloaded from the US Treasury; refresh it with `python scripts/update_ofac.py` (run at least daily in production).
