# FMS: A Privacy-Preserving, Deterministic RegTech Platform for AML/CFT Compliance at Under-Resourced U.S. Financial Institutions

**Tochukwu Iloani**
*July 2026 · Version 1.1*

---

## Abstract

Anti-Money Laundering (AML) and Countering the Financing of Terrorism (CFT) compliance sits at the intersection of national security, cybersecurity, and financial-infrastructure resilience. Yet community banks, credit unions, money services businesses, and fintech startups carry the same Bank Secrecy Act (BSA) obligations as the largest institutions — suspicious-activity monitoring, currency-transaction reporting, and sanctions screening — while rarely affording the enterprise platforms built to meet them, and while legacy compliance tools often require risky, direct connectivity into core banking databases. This paper presents **FMS (Fraud Monitoring System)**, an open-source, privacy-preserving regulatory-technology (RegTech) platform for that underserved segment. FMS pairs a fully deterministic, explainable detection engine with OFAC sanctions screening and FinCEN-aligned CTR/SAR identification and filing preparation, and it ingests transactions two ways: a secure, webhook/API push model requiring **no database access** — institutions send transaction events and receive a risk verdict synchronously — or a read-only database poll for on-premises deployments. The push model applies **zero-trust principles**: no implicit trust of, or inbound connectivity into, an institution's database; authenticated ingestion; and HMAC-signed result exchange — materially reducing the attack surface of traditional AML integrations. We describe the architecture, detection methodology, and security model; argue that determinism and explainability are *requirements*, not compromises, for examinable compliance tooling; and state plainly what the system does not yet do. FMS is decision support for a human compliance officer, never a replacement.

---

## 1. The problem: a compliance gap at the bottom of the market

The integrity of a payment system is only as strong as its weakest monitored node. In the United States, the BSA and its implementing regulations impose monitoring and reporting duties on virtually every institution that moves money:

- **Currency Transaction Reports (CTRs)** for currency transactions exceeding $10,000 in a business day, including aggregated smaller transactions (31 CFR 1010.311, 1010.313);
- **Suspicious Activity Reports (SARs)** for suspicious activity aggregating $5,000 or more where a suspect can be identified (31 CFR 1020.320) — and for *structuring* at any amount (31 CFR 1010.314);
- **OFAC sanctions compliance**: transactions involving parties on the Specially Designated Nationals (SDN) list must be blocked or rejected and reported (31 CFR Part 501).

Large banks meet these duties with commercial AML platforms whose licensing, integration, and tuning costs routinely run into six or seven figures. Small institutions — the several thousand US community banks and credit unions, and a growing population of fintechs and MSBs — face the same examiners with a fraction of the budget. The practical result is a structural gap: the institutions least able to detect financial crime are also the ones criminals can most cheaply probe. Money laundering, elder fraud, business-email-compromise, and structuring schemes do not respect institutional size; the reporting regime assumes monitoring that many small institutions struggle to afford.

FMS is an attempt to close part of that gap with open-source software: monitoring that is *credible* — aligned with the actual regulatory framework, explainable to an examiner, honest about its limits — while being deployable by a single technical operator.

The problem is one of national importance, not merely commercial convenience. Under-monitored institutions are precisely the channels illicit finance seeks out; strengthening their detection capability supports the U.S. Department of the Treasury's stated modernization of the AML/CFT regime toward effective, risk-based, technology-driven compliance, and contributes to the security and resilience of the national payment system. Lowering the cost and integration risk of credible monitoring is therefore a matter of financial-infrastructure resilience and, by extension, economic and national security.

## 2. Design principles

Three principles drove every architectural decision.

**2.1 Determinism over black boxes.** Every detection decision in FMS is produced by explicit, inspectable rules: threshold comparisons, rolling-window aggregations, z-score bands against an account's own history. There is no machine-learning classifier in the decision path. This is a deliberate position, not a limitation of ambition: supervisory guidance on model risk (FRB SR 11-7 / OCC 2011-12) expects institutions to explain and validate what their models do, and an alert that cannot be explained cannot be defended in an examination — or acted on confidently by an analyst. Every FMS alert carries the complete list of signals that fired, each with a plain-English reason containing the actual numbers involved.

**2.2 The machine flags; the human decides.** FMS never blocks a transaction, files a report, or closes a case on its own. It surfaces activity, computes obligations, prepares filing worksheets, and tracks deadlines; a named human confirms, dismisses, or escalates — and that decision is recorded immutably with their identity. This division of labor matches both regulatory reality (filings are the institution's responsibility) and operational safety (a false positive that blocks a legitimate payroll is its own harm).

**2.3 Data stays home by default.** In its default configuration FMS makes no external calls with transaction data. The optional AI feature — a natural-language case summary — is off by default, never participates in detection, and can be pointed at a self-hosted model so that even prose generation never leaves the institution's infrastructure.

**2.4 Minimize the integration attack surface (zero-trust ingestion).** Traditional AML tools require standing, privileged connectivity into a core banking database — a persistent, high-value attack surface and a common objection from security-conscious U.S. fintechs. FMS's primary integration inverts this: the institution *pushes* transaction events to an authenticated endpoint and receives a verdict, so FMS holds no database credentials and opens no inbound path to the core. This reflects zero-trust principles — nothing is trusted by location or network position; every exchange is authenticated and integrity-protected (HMAC-signed) — rather than a formally certified zero-trust framework. A read-only database poll remains available for on-premises institutions that prefer it.

## 3. System architecture

FMS supports two ingestion models over a common detection core:

```
        ┌─ API push (primary): institution POSTs events ─┐   (no DB access)
        │      X-API-Key auth → synchronous verdict       │
Institution ───────────────────────────────────────────► Ingestion
        │                                                 │
        └─ Read-only DB poll (on-prem): MySQL / SQL       ┘
           Server / PostgreSQL / Oracle
                                                               │
                                              Deterministic detection engine
                                              + OFAC sanctions screening
                                              + CTR / SAR assessment
                                                               │
                                     Application DB ───┬──▶ REST API (FastAPI)
                                  (cases, users, audit) │      ├─ case management
                                                        │      ├─ filing worksheets
                                                        │      └─ live alert feed (WebSocket)
                                                        └──▶ Web dashboard (Next.js)
```

**Ingestion.** FMS accepts transactions two ways over the same detection core. In **API-push mode** (the primary, privacy-preserving model), the institution POSTs each transaction to an API-key-authenticated endpoint and receives the risk verdict in the same response; FMS stores no database credentials and the institution's core has no inbound exposure. Behavioral history for these accounts is built from FMS's own append-only ingested-transaction store, so the full engine operates with zero database access. In **DB-poll mode** (for on-premises institutions that prefer it), a poller reads new transactions read-only through a small adapter interface — MySQL, SQL Server, PostgreSQL, and Oracle are implemented — with a column-mapping configuration that adapts to arbitrary schemas without code changes; FMS never writes to the source database. In both modes processing is *idempotent and never-miss by construction*: results are committed durably before any checkpoint advances, failed analyses are retried rather than skipped, and a uniqueness constraint on the source transaction id prevents duplicate cases on replay or crash recovery.

**Detection engine.** Each transaction is analyzed against the account's own recent history (default 90 days). The engine computes a 0–100 risk score as a sum of named components (§4), assesses CTR and SAR obligations independently of the fraud verdict, and screens the counterparty against the OFAC SDN list (§5). Analysis is resilient to component failure: the optional AI summary can fail or be disabled with no effect on detection.

**Application store.** Cases, user accounts, and the audit log live in a server database (SQL Server or PostgreSQL-compatible via SQLAlchemy; SQLite for development), separate from the banking database.

**Interface.** A web dashboard provides the operational surface: a real-time alert queue, full transaction log, per-customer rollups, case workflow, a transparent view of the live rule configuration, analytics with honestly-computed KPIs, filing reports with deadline tracking, per-user audit investigation, and administration. A WebSocket feed pushes new alerts to connected analysts; email alerting is available for off-dashboard notification.

**Result delivery (outbound).** Complementing push ingestion, FMS can post results *back* to the institution's endpoint — a `case.flagged` event on detection and a `case.disposition` event when a human confirms, dismisses, or escalates — each HMAC-SHA256 signed so the receiver can verify authenticity and integrity. This closes the loop for the zero-trust model: a partner integrates entirely over authenticated, signed HTTPS in both directions, with no shared database and no standing network path into either system.

## 4. Detection methodology

### 4.1 Regulatory thresholds
CTR assessment implements both the single-transaction threshold and same-day, same-direction aggregation. Thresholds are currency-aware (USD $10,000 per the BSA; local-currency equivalents for other jurisdictions) and maintained in one documented table. SAR assessment applies the $5,000 bar — and, critically, recommends a SAR for structuring-pattern signals *regardless of amount*, reflecting 31 CFR 1010.314. CTR and SAR are modeled as independent tracks: a large routine transfer can require a CTR while being entirely unsuspicious, and a pattern of small deposits can warrant a SAR with no CTR at all. Conflating these two obligations is a common error in ad-hoc tooling; FMS keeps them distinct end to end.

### 4.2 Behavioral and pattern signals
The risk score sums named components, each with a bounded contribution, including:

- **Structuring band** — amounts falling just below the reporting threshold (default band: 90–100%);
- **Velocity clustering** — multiple sub-threshold transfers across a rolling window (default 5 days) that aggregate above the threshold;
- **Multi-source smurfing** — three or more distinct senders funding one account within 48 hours, aggregating above the threshold;
- **Same-counterparty accumulation** — same-day outward payments to one recipient crossing the threshold cumulatively;
- **Behavioral deviation** — z-score bands of the amount against the account's own baseline, with separate handling for new accounts that have no baseline;
- **Contextual signals** — first-time counterparty, unusual hours, first use of a channel, same-day velocity;
- **Suppression signals** — payroll/batch payment references and established high-value patterns *reduce* the score, addressing the dominant source of false positives in amount-based rules.

Score bands map to LOW / MEDIUM / HIGH / CRITICAL, but hard money-laundering signals (structuring, smurfing) open a case regardless of the total score, because structuring is reportable irrespective of amount. Every threshold, window, band, and weight is documented with its rationale in the project's model documentation (MODEL.md), which also records what the test suite validates — the documentation layer of a model-risk-management program.

### 4.3 Typology attribution
Flagged cases receive a human-meaningful typology — *multi-source smurfing*, *invoice fraud*, *account takeover*, *suspicious large payment* — assigned by transparent rules over which signals fired. The label orients the analyst; the underlying reasons remain the evidence.

## 5. Sanctions screening

Every counterparty name is screened against the OFAC SDN list (primary names plus aliases; ~40,000 entries), refreshed from the US Treasury's published files automatically on a schedule (default daily) with a manual operator script as a fallback. In API-push mode the account holder name may also be supplied and is screened alongside the counterparty. Matching is normalized (case, punctuation, corporate suffixes, token order) and fuzzy (token-overlap and sequence similarity) with a conservative default threshold of 0.90 to control false positives. A trigram candidate index reduces per-transaction screening cost from seconds to single-digit milliseconds against the full list, making per-transaction screening viable on modest hardware.

A confirmed-format SDN match **overrides** the behavioral score entirely: the case is forced to the highest severity with an explicit block-or-reject instruction, reflecting that OFAC obligations are absolute rather than risk-weighted. The match evidence (matched entry, sanctions program, similarity score) is presented for human adjudication, and the interface reminds the analyst that name screening can produce false positives. An optional politically-exposed-persons list is supported with a distinct, non-blocking "enhanced due diligence" treatment — because PEP status is a risk factor, not a prohibition.

## 6. Case management, accountability, and access control

Alerts become **cases** with a lifecycle (open → under review → confirmed / dismissed / escalated). Every action is attributed to the authenticated user who took it — identity comes from the session, never from client-supplied text — and lands in a system-wide audit trail alongside sign-ins (including failures), configuration changes with field-level before/after values, password resets, and role changes.

Access control is a three-tier model enforced server-side: **administrators** (full access including configuration and user management), **analysts** (view and act on cases), and **viewers** (read-only). The interface reflects these roles, but enforcement lives in the API — a viewer's request to action a case is rejected with 403 regardless of what the client renders. Authentication uses email + password with PBKDF2-hashed credentials, HMAC-signed expiring session tokens, per-IP login throttling, and admin-driven or email-based password recovery.

## 7. Regulatory outputs

FMS maintains two filing pipelines:

- **CTR** — a continuously maintained list of reportable transactions with their triggers, exportable as CSV or as **FinCEN Form 112-shaped worksheets** with the institution's details pre-filled and the fields FMS cannot know (KYC identifiers) explicitly enumerated for manual completion.
- **SAR** — recommended SARs with the detection date, the **30-day filing deadline**, days remaining, and Form 111-shaped worksheets including a draft narrative assembled from the deterministic reasons.

FMS deliberately does **not** transmit filings. E-filing requires institution-level enrollment with FinCEN, and the final narrative and determination are an officer's responsibility. The system's contract is: *nothing reportable slips by unnoticed, and everything needed to file is one export away.*

## 8. Security model

- **Least privilege at the data source:** read-only database access; the documentation instructs operators to provision a read-only account.
- **Separation of stores:** the application database (cases, users, audit) is distinct from the banking database.
- **Credential hygiene:** passwords hashed (PBKDF2-SHA256, per-password salts); secrets never returned by the API; database passwords never displayed after entry.
- **Transport and headers:** TLS options for database connections; standard security response headers (HSTS, nosniff, frame-deny, referrer suppression); per-IP login rate limiting.
- **No default egress:** with AI summaries off (the default), FMS makes no external calls carrying transaction data; the OFAC list refresh pulls *from* Treasury and sends nothing.
- **Tested security core:** the password, token, and role-capability logic is covered by unit tests run in continuous integration, so access-control regressions fail the build.

## 9. Honest limitations

Credibility in compliance tooling requires stating what a system does *not* do.

1. **No machine-learning detection.** FMS will not catch novel patterns outside its rule set. This is the accepted cost of full explainability at this stage; the rules cover the well-documented core typologies.
2. **No model validation against labeled outcomes.** Thresholds are documented, reasoned heuristics — not yet tuned against an institution's confirmed-fraud history. The methodology document defines the tuning procedure an adopting institution should run; FMS records the officer decisions (confirm/dismiss) that make future above/below-the-line analysis possible.
3. **Name-only sanctions screening.** Screening does not yet incorporate dates of birth, addresses, identification numbers, or phonetic matching, and screens transaction counterparties rather than the full customer base.
4. **Detection and containment, not inline interdiction.** In API-push mode a synchronous verdict is returned as the transaction is submitted, so the institution *may* choose to act pre-settlement using that verdict; FMS itself, however, does not sit inline in the payment rail and does not reject payments on the institution's behalf. In DB-poll mode it observes transactions after they post (seconds of latency). In both cases the design supports rapid human containment — alert, hold, freeze — rather than automated blocking.
5. **"Zero-trust" is an architectural posture, not a certification.** The push model applies zero-trust *principles* (no implicit database trust, authenticated ingestion, HMAC-signed exchange, least-privilege read-only DB access when polling). It has not been assessed against a formal zero-trust maturity framework (e.g., NIST SP 800-207) or independently audited.
6. **Single-node scope.** The current deployment model is one backend node; login throttling and WebSocket state are in-process. Multi-node deployment requires shared state and is future work.
7. **Operational security is the deployer's.** HTTPS termination, secrets management, database encryption at rest, and MFA are deployment-environment responsibilities documented, but not provided, by the project.

## 10. Related context

Commercial AML suites (e.g., NICE Actimize, Oracle FCCM, Verafin) offer broader typology coverage, learning-based detection, and vendor support at costs generally out of reach for the institutions FMS targets. Open-source AML tooling remains sparse and largely component-level (matching libraries, rule engines) rather than deployable end-to-end systems with case management and filing preparation. FMS's contribution is the *integration*: a coherent, standards-aligned, operable whole — engine, screening, workflow, audit, reporting — under an MIT license.

## 11. Conclusion

Financial-crime monitoring should not be a luxury good. The regulatory framework already tells us what must be watched for; the barrier for small institutions has been the cost of credible software, not the mystery of the requirements. FMS demonstrates that a deterministic, explainable, auditable monitoring platform — one a compliance officer can defend line-by-line to an examiner — can be built and given away. The system is open source under the MIT license, self-hostable in one command, and designed from its first line to keep a human being, identified and accountable, at the center of every decision that matters.

---

## References

1. 31 CFR § 1010.311 — Filing obligations for reports of transactions in currency.
2. 31 CFR § 1010.313 — Aggregation of currency transactions.
3. 31 CFR § 1020.320 — Reports by banks of suspicious transactions.
4. 31 CFR § 1010.314 — Structured transactions.
5. 31 CFR Part 501 — Reporting, procedures and penalties (OFAC).
6. FFIEC BSA/AML Examination Manual.
7. Board of Governors of the Federal Reserve System, SR 11-7: *Guidance on Model Risk Management* (2011); OCC Bulletin 2011-12.
8. US Department of the Treasury, Office of Foreign Assets Control — Specially Designated Nationals and Blocked Persons List.
9. FinCEN — BSA E-Filing System; FinCEN Form 112 (CTR); FinCEN Form 111 (SAR).

---

*FMS project documentation: README (system overview), MODEL.md (detection methodology and parameters), COMPLIANCE.md (regulatory alignment), docs/USER_MANUAL.md (operator manual).*
