# FMS — The Transaction Assessment Pipeline

*A technical whitepaper: how a single transaction travels from arrival to a compliance case, and the exact code that decides its fate at each step.*

> **How to read this.** We follow **one transaction** from the moment it reaches FMS to the moment a compliance officer sees a case. At each stage we name the engine, explain what it does and why, then show the **real code** that does it — with a `file:line` reference so you can open the source and confirm every excerpt. Nothing here is paraphrased. Where a long function is trimmed for readability, the cut is marked `# …`.

---

## The shape of the system

FMS is a monitoring engine wrapped in an API. A transaction can arrive two ways, but **both funnel into one analysis path**, so the detection logic is identical no matter how the data got in:

```
                    ┌─────────────────────────────────────────────┐
  PULL mode         │                                             │
  bank DB ──poller──┤                                             │
                    │        analyzer.analyze(txn, history)       │──► FraudCase ──► officer
  PUSH mode         │   (profile ▸ risk ▸ CTR ▸ SAR ▸ sanctions   │      (DB)        (UI / alerts)
  POST /ingest ─────┤          ▸ reasons ▸ summary)               │
                    │                                             │
                    └─────────────────────────────────────────────┘
```

| Stage | Module | Responsibility |
|---|---|---|
| 1. Arrival | `routers/ingest.py`, `services/poller.py`, `adapters/*` | Receive/fetch a transaction, normalize its shape |
| 2. Store & history | `models.py`, adapters | Persist it; pull the account's recent history |
| 3. Orchestration | `ingest.py::run_ingest`, `poller.py::_process_table` | Drive the assessment and record the outcome |
| 4. Analysis engines | `services/analyzer.py`, `services/sanctions.py` | Profile, score, assess CTR/SAR, screen sanctions, explain |
| 5. Verdict & alerting | `models.py::FraudCase`, `broadcaster`/`emailer`/`callbacks` | Save the case, notify in real time |

---

## Stage 1 — Arrival

### Every transaction becomes one shape

No matter the source — MySQL, Postgres, Oracle, SQL Server, or a JSON POST — the first thing FMS does is force the data into a single internal shape. Everything downstream speaks only this type, which is why the same engine serves every bank.

```python
# backend/adapters/base.py:17
@dataclass
class NormalizedTransaction:
    id: str
    account_id: str
    amount: float
    direction: str          # INWARD / OUTWARD
    timestamp: datetime
    counterparty_account: str | None
    counterparty_name: str | None
    channel: str | None
    currency: str
    reference: str | None
    status: str | None
    source_table: str       # which config table key this came from
    batch_id: str | None = None   # optional — set when bank table has a batch/payment-run ID column
```

### Mode A — Pull: watching the bank's database

In pull mode a background poller connects to the bank's own database and reads new rows. Each database vendor hides behind one interface, so the poller never knows or cares which engine it's talking to:

```python
# backend/adapters/base.py:34
class BaseAdapter(ABC):
    @abstractmethod
    async def fetch_new_transactions(
        self, table_key: str, since_id: str | None, limit: int = 100
    ) -> list[NormalizedTransaction]: ...

    @abstractmethod
    async def fetch_account_history(
        self, account_id: str, table_keys: list[str], history_days: int = 90
    ) -> list[NormalizedTransaction]: ...
```

The right adapter is chosen from config at runtime — this is the whole vendor-selection logic:

```python
# backend/services/poller.py:24
def get_adapter() -> BaseAdapter:
    global _adapter
    if _adapter is None:
        db_type = bank_config.get("database", {}).get("type", "mysql").lower()
        kwargs = dict(db_config=bank_config["database"], tables_config=bank_config.get("tables", {}))
        if db_type == "mssql":
            from backend.adapters.mssql import MSSQLAdapter as A
        elif db_type in ("postgres", "postgresql"):
            from backend.adapters.postgres import PostgresAdapter as A
        elif db_type == "oracle":
            from backend.adapters.oracle import OracleAdapter as A
        else:
            from backend.adapters.mysql import MySQLAdapter as A
        _adapter = A(**kwargs)
    return _adapter
```

### Mode B — Push: the bank POSTs each transaction

For institutions that won't grant database access, FMS exposes a locked-down endpoint. The request is validated at the door by a strict schema — bad shapes never reach the engine:

```python
# backend/routers/ingest.py:53
class TxnIn(BaseModel):
    external_id: str = Field(..., max_length=128)   # caller's unique transaction id
    account_id: str = Field(..., max_length=64)
    amount: float = Field(..., gt=0)
    direction: str = Field(..., pattern="^(INWARD|OUTWARD)$")
    timestamp: datetime | None = None               # defaults to now (UTC)
    counterparty_account: str | None = Field(None, max_length=64)
    counterparty_name: str | None = Field(None, max_length=200)
    channel: str | None = Field(None, max_length=40)
    currency: str = Field("USD", max_length=10)
    reference: str | None = Field(None, max_length=255)
    account_holder_name: str | None = Field(None, max_length=200)  # screened against OFAC if given
```

The endpoint itself refuses to run without an API key — an open ingestion endpoint would let anyone pollute the case queue:

```python
# backend/routers/ingest.py:38
async def require_ingest_key(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    key = (settings.fms_ingest_api_key or settings.fms_api_key).strip()
    if not key:
        raise HTTPException(status_code=503, detail="Ingestion disabled: set FMS_INGEST_API_KEY on the server first")
    if x_api_key != key:
        await audit.record("api-client", "INGEST_KEY_REJECTED", ... )   # probing shows up in Security Events
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key")
```

---

## Stage 2 — The store, and the account's history

A pushed transaction is written to FMS's own history store. This is what lets push-mode banks get the *full* behavioral engine (structuring, smurfing, velocity) without ever exposing their database — FMS remembers what it has seen:

```python
# backend/models.py:158
class IngestedTransaction(Base):
    """Transactions received via the push API — FMS's own history store for
    institutions that feed us events instead of granting database access."""
    __tablename__ = "ingested_transactions"
    __table_args__ = (
        UniqueConstraint("external_id", name="uq_ingested_external_id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(String(128))       # caller's transaction id
    account_id: Mapped[str] = mapped_column(String(64), index=True)
    amount: Mapped[float] = mapped_column(Float)
    # … direction, timestamp, counterparty, channel, currency, reference, account_holder_name
```

Behavioral analysis is meaningless without context, so before scoring anything FMS pulls the account's recent history — every prior transaction for this account inside the configured window:

```python
# backend/routers/ingest.py:104
history_days = int(bank_config.get("monitoring", {}).get("history_days", 90))
cutoff = ts - timedelta(days=history_days)
hist_rows = (await db.execute(
    select(IngestedTransaction)
    .where(IngestedTransaction.account_id == body.account_id,
           IngestedTransaction.timestamp >= cutoff,
           IngestedTransaction.external_id != body.external_id)   # exclude the txn itself
    .order_by(IngestedTransaction.timestamp.desc())
)).scalars().all()
```

*(In pull mode the equivalent is `adapter.fetch_account_history(...)` in `poller.py:105`.)* The transaction plus its history are now everything the engine needs.

---

## Stage 3 — The orchestrator: one call does the assessment

Both arrival paths converge on a single line. Everything the engine decides happens inside `analyzer.analyze(txn, history)`:

```python
# backend/routers/ingest.py:114
txn = _to_normalized(row)
result = await analyzer.analyze(txn, [_to_normalized(h) for h in hist_rows])
```

In pull mode the poller wraps that same call with two guarantees that matter for a compliance tool — **never double-flag**, and **never silently drop**:

```python
# backend/services/poller.py:95   (inside the per-transaction loop)
# Idempotency guard: a crash/replay must not re-flag a transaction that
# already produced a case.
if await _case_exists(txn.source_table, txn.id):
    await _save_checkpoint(table_key, txn.id)
    continue

history = await adapter.fetch_account_history(txn.account_id, table_keys, history_days)
history = [h for h in history if h.id != txn.id]

result = await analyzer.analyze(txn, history)
# … build & commit the FraudCase …

# Advance the checkpoint only AFTER the case is durably committed. If we crash
# before this, the transaction is re-fetched next cycle and the dedup guard above
# prevents a duplicate case.
await _save_checkpoint(table_key, txn.id)
```

That ordering is deliberate and is called out in the code itself:

```python
# backend/services/poller.py:190
except Exception as e:
    # A transient error — do NOT advance the checkpoint. Retry the same
    # transaction next poll rather than skipping it. Never-miss beats
    # never-stall for a compliance tool.
    log.error(f"[{table_key}] Error processing txn {txn.id}: {e} — will retry next cycle")
    raise
```

---

## Stage 4 — Inside `analyze()`: the engine room

`analyze()` first calls `evaluate()`, which is the **deterministic verdict core** — the whole rules-only decision, no network, no LLM:

```python
# backend/services/analyzer.py:812
def evaluate(txn: NormalizedTransaction, history: list[NormalizedTransaction]) -> dict:
    threshold = _ctr_threshold(txn.currency)
    profile   = _compute_behavioral_profile(history, threshold)
    ctr       = _assess_ctr(txn, history, threshold)
    risk      = _compute_risk_score(txn, history, profile, threshold)

    has_hard_signal = bool(_HARD_FRAUD_SIGNALS & risk.components.keys())
    if risk.level == "LOW" and not has_hard_signal:
        is_fraudulent, confidence = False, "LOW"
    elif risk.level == "MEDIUM":
        is_fraudulent, confidence = True, "MEDIUM"
    else:
        is_fraudulent, confidence = True, "HIGH"

    sar_recommended, sar_reason = _assess_sar(txn, risk, is_fraudulent, threshold)
    return {"threshold": threshold, "profile": profile, "ctr": ctr, "risk": risk,
            "is_fraudulent": is_fraudulent, "confidence": confidence,
            "sar_recommended": sar_recommended, "sar_reason": sar_reason}
```

Read that top to bottom and you have the pipeline: **threshold → profile → CTR → risk → verdict → SAR.** Now each engine in turn.

### 4.1 · The rule numbers (currency-aware thresholds)

Every decision anchors to the CTR threshold. FMS keys it by currency, with the US Bank Secrecy Act figure as the reference and the regulation cited in the source:

```python
# backend/services/analyzer.py:63
# Cash-transaction reporting threshold. In the US this is the FinCEN / Bank
# Secrecy Act CTR threshold (USD 10,000, per 31 CFR 1010.311). Other rows are
# the local-currency equivalents for jurisdictions we've onboarded.
_CTR_THRESHOLDS: dict[str, float] = {
    "USD": 10_000,
    "NGN": 15_000_000,   # ~$10k at ≈1,500 NGN/USD
    "GBP": 8_000,
    "EUR": 9_000,
    # … CAD, AUD, GHS, ZAR
}

# SAR threshold — half the CTR threshold (31 CFR 1020.320). Structuring is
# reportable regardless of amount, which _assess_sar() handles separately.
SAR_RATIO = 0.5
```

```python
# backend/services/analyzer.py:153
def _ctr_threshold(currency: str) -> float:
    return _CTR_THRESHOLDS.get((currency or "USD").upper(), 10_000)

def _sar_threshold(currency: str) -> float:
    return _ctr_threshold(currency) * SAR_RATIO
```

### 4.2 · The behavioral profiler — "what is normal for this account?"

Before judging a transaction, the engine builds a statistical portrait of the account from its history: typical size, spread, known counterparties, active channels. This baseline is the yardstick everything is measured against.

```python
# backend/services/analyzer.py:387
def _compute_behavioral_profile(history, threshold) -> BehavioralProfile:
    if not history:
        return BehavioralProfile(transaction_count=0, avg_amount=0.0, ... )   # new account
    amounts = [h.amount for h in history]
    avg = statistics.mean(amounts)
    std = statistics.stdev(amounts) if len(amounts) > 1 else 0.0
    cutoff = datetime.utcnow() - timedelta(days=7)
    return BehavioralProfile(
        transaction_count=len(history),
        avg_amount=round(avg, 2),
        max_amount=max(amounts),
        std_dev=round(std, 2),
        ctr_level_count=sum(1 for a in amounts if a >= threshold),
        large_txn_pct=round(sum(1 for a in amounts if a >= threshold * 0.5) / len(amounts) * 100, 1),
        known_counterparties=len({h.counterparty_account for h in history if h.counterparty_account}),
        active_channels=list({h.channel for h in history if h.channel}),
        days_active=len({h.timestamp.date() for h in history if isinstance(h.timestamp, datetime)}),
        recent_7d_count=sum(1 for h in history if isinstance(h.timestamp, datetime) and h.timestamp >= cutoff),
    )
```

### 4.3 · The risk engine — the deterministic scorer

This is the heart. It compares the transaction against the profile and the rules, accumulating a score out of **named components** — each carrying its own score *and* a human-readable reason. Two representative bands: first, a *systematic-payment* signal that lowers suspicion, then the core *behavioral deviation* measured as a z-score from the account's norm.

```python
# backend/services/analyzer.py:417
def _compute_risk_score(txn, history, profile, threshold) -> RiskScoreResult:
    score = 0
    components: dict = {}
    behavioral_verdict = "CONSISTENT"
    # …
    # ── 0. Batch / systematic payment signal (-20) ──
    batch_ref = _detect_batch(txn)
    if batch_ref:
        components["batch_payment"] = {
            "score": -20,
            "reason": f"Transaction carries a systematic/batch payment reference: '{batch_ref}'",
        }
        score -= 20

    # ── 1. Behavioral deviation: how far from the account's norm (0-35) ──
    if profile.transaction_count == 0:
        dev_pts = 20 if txn.amount >= threshold * 0.5 else 10
        behavioral_verdict = "NEW_ACCOUNT"
        components["new_account_risk"] = {"score": dev_pts, "reason": "No prior transaction history …"}
    else:
        z = ((txn.amount - profile.avg_amount) / profile.std_dev
             if profile.std_dev > 0
             else (5.0 if txn.amount > profile.avg_amount else 0.0))
        if   z <= 1: dev_pts, behavioral_verdict = 0,  "CONSISTENT"
        elif z <= 2: dev_pts, behavioral_verdict = 10, "UNUSUAL"
        elif z <= 3: dev_pts, behavioral_verdict = 22, "UNUSUAL"
        else:        dev_pts, behavioral_verdict = 35, "ANOMALOUS"
        # …
```

The key design point, visible in the code: **the score is never a black box.** Each component is a `{score, reason}` pair, so the number can always be explained back to a plain-English cause. (The full function also scores near-threshold structuring, rolling-window velocity, inbound smurfing, new counterparty/channel, and odd-hours — same pattern throughout.)

### 4.4 · The CTR engine — is a Currency Transaction Report legally required?

Purely mechanical and objective: single transaction over the threshold, or same-day same-direction aggregate over it.

```python
# backend/services/analyzer.py:262
def _assess_ctr(txn, history, threshold) -> CTRAssessment:
    if txn.amount >= threshold:
        return CTRAssessment(required=True,
            reason=f"Single transaction of {txn.currency} {txn.amount:,.2f} exceeds CTR threshold",
            trigger="SINGLE_TXN")

    today = txn.timestamp.date() if isinstance(txn.timestamp, datetime) else None
    if today:
        same_day = [h for h in history
                    if isinstance(h.timestamp, datetime)
                    and h.timestamp.date() == today and h.direction == txn.direction]
        day_total = sum(h.amount for h in same_day) + txn.amount
        if day_total >= threshold:
            return CTRAssessment(required=True,
                reason=f"Same-direction day aggregate: {txn.currency} {day_total:,.2f} across {len(same_day)+1} transactions",
                trigger="SAME_DAY_AGGREGATE")
    return CTRAssessment(required=False, reason="", trigger="NONE")
```

### 4.5 · The SAR engine — is a Suspicious Activity Report recommended?

Judgemental, not mechanical. Structuring/smurfing is reportable **at any amount** — the pattern itself is the suspicious activity; otherwise a suspicious amount at/above the SAR threshold triggers it.

```python
# backend/services/analyzer.py:299
_STRUCTURING_SIGNALS = frozenset(
    {"near_threshold_amount", "near_miss_spike", "velocity_clustering",
     "outward_smurfing", "multi_source_smurfing"})

# backend/services/analyzer.py:305
def _assess_sar(txn, risk, is_fraudulent, ctr_threshold) -> tuple[bool, str]:
    if not is_fraudulent:
        return False, ""
    structuring = _STRUCTURING_SIGNALS & risk.components.keys()
    if structuring:
        return True, (f"Potential structuring/smurfing pattern detected ({', '.join(sorted(structuring))}) "
                      f"— reportable on a SAR regardless of amount.")
    sar_threshold = ctr_threshold * SAR_RATIO
    involved = max(txn.amount,
                   risk.rolling_5d_total if risk.rolling_5d_count > 1 else 0.0,
                   risk.inbound_total_48h)
    if involved >= sar_threshold:
        return True, (f"Suspicious activity involving {txn.currency} {involved:,.2f} meets the "
                      f"{txn.currency} {sar_threshold:,.0f} SAR reporting threshold …")
    return False, ""
```

### 4.6 · Systematic-payment suppression — killing the obvious false alarm

A payroll run or supplier batch should not score like a one-off transfer to a stranger. Before the behavioral checks bite, the engine recognises a batch by an explicit `batch_id` or a reference pattern:

```python
# backend/services/analyzer.py:93
_BATCH_PATTERN = re.compile(
    r"\b(batch|payroll|pay[\s\-]?run|salary|salaries|wages|bulk|sweep|"
    r"standing[\s\-]?order|scheduled|auto[\s\-]?debit|direct[\s\-]?debit|"
    r"regular[\s\-]?payment|monthly[\s\-]?payment|quarterly|disbursement)\b", re.IGNORECASE)

# backend/services/analyzer.py:161
def _detect_batch(txn) -> str | None:
    if txn.batch_id:
        return txn.batch_id
    if txn.reference and _BATCH_PATTERN.search(txn.reference):
        return txn.reference
    return None
```

### 4.7 · Sanctions screening — the override that outranks everything

Sanctions are **strict liability**, so a listed counterparty overrides the behavioral score entirely: a match forces the case to HIGH regardless of how benign the pattern looked. PEP matches are different in kind — enhanced due diligence, not a block — so they annotate rather than override.

```python
# backend/services/analyzer.py:851   (inside analyze(), after the deterministic verdict)
sanctions_match = sanctions.screen(txn.counterparty_name)
sanctions_hit = sanctions_match is not None and sanctions_match.list_type == "SDN"
if sanctions_match and sanctions_match.list_type == "SDN":
    is_fraudulent = True
    confidence = "HIGH"
    fraud_type = "sanctions match"
    reasons = [f"OFAC SANCTIONS MATCH — {sanctions_detail}. This is a listed party: the "
               f"transaction must be blocked or rejected and reported to OFAC …"] + reasons
elif sanctions_match and sanctions_match.list_type == "PEP":
    reasons = [f"POLITICALLY EXPOSED PERSON — … enhanced due diligence is expected …"] + reasons
```

The matcher itself is deliberately transparent — every hit is explainable, because a screening aid a human must adjudicate cannot be a black box:

```python
# backend/services/sanctions.py:1  (module docstring)
# Matching is intentionally transparent (normalized exact + token-overlap +
# string similarity) so every hit is explainable. It is a screening aid, not a
# determination — a human must adjudicate every alert.

# backend/services/sanctions.py:79
def _normalize(name: str | None) -> str:
    n = (name or "").upper()
    n = re.sub(r"[^A-Z0-9 ]", " ", n)
    tokens = [t for t in n.split() if t and t not in _NOISE_TOKENS]   # strip LTD/INC/CORP noise
    return " ".join(tokens)
```

### 4.8 · Reasons and the summary — deterministic first, AI only as prose

The reasons a case carries are generated **deterministically** — there is no hallucination risk, because they are templated from the risk components:

```python
# backend/services/analyzer.py:842
# Reasons are generated deterministically — no hallucination risk
reasons = _plain_reasons(txn, risk, profile, ctr, threshold)
fraud_type = _pick_fraud_type(risk) if is_fraudulent else None
```

An LLM is **opt-in** and only ever writes the human-readable prose summary — it never influences whether a case is raised, and if it fails the engine falls back to a deterministic summary. This is the single most important property of the whole system, stated in the code:

```python
# backend/services/analyzer.py:939
# AI summaries are opt-in (FMS_AI_SUMMARIES). By DEFAULT the deterministic
# engine writes the summary and no transaction data leaves the host. When
# enabled, the LLM only produces the human-readable prose — it never
# influences whether a case is raised (that is all computed above).
summary = ""
if settings.ai_summaries.strip().lower() in ("on", "true", "1", "yes"):
    try:
        raw = await _generate_summary_text(SYSTEM_PROMPT, summary_prompt)
        # … parse JSON …
    except Exception as e:
        log.warning(f"LLM summary unavailable ({e}) — using deterministic fallback")
if not summary:
    summary = _fallback_summary(txn, risk, profile, reasons, ctr)
```

`analyze()` returns a single `FraudAnalysis` carrying the verdict, the risk score, the CTR/SAR determinations, the sanctions result, the reasons, and the summary.

---

## Stage 5 — The verdict lands: a case, and an alert

The orchestrator writes the result into one durable record. Note the unique constraint — the database itself guarantees one transaction can only ever become one case:

```python
# backend/models.py:17
class FraudCase(Base):
    __tablename__ = "fraud_cases"
    __table_args__ = (
        UniqueConstraint("source_table", "source_txn_id", name="uq_case_source_txn"),  # no duplicate cases
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    account_id: Mapped[str] = mapped_column(String(64), index=True)
    amount: Mapped[float] = mapped_column(Float)
    # Analysis
    risk_score:      Mapped[int | None]  = mapped_column(Integer, nullable=True)
    ctr_required:    Mapped[bool]        = mapped_column(Boolean, default=False)
    sar_recommended: Mapped[bool]        = mapped_column(Boolean, default=False)
    sanctions_hit:   Mapped[bool]        = mapped_column(Boolean, default=False)
    confidence:      Mapped[str]         = mapped_column(String(10))   # HIGH / MEDIUM / LOW
    fraud_type:      Mapped[str | None]  = mapped_column(String(50), nullable=True)
    reasons:         Mapped[list]        = mapped_column(JSON, default=list)
    ai_summary:      Mapped[str | None]  = mapped_column(Text, nullable=True)
    status:          Mapped[str]         = mapped_column(String(30), default="OPEN", index=True)
    # …
```

If the transaction was flagged, the officer is told immediately — a live push to the dashboard plus email/webhook, all fired off the request path so nothing blocks:

```python
# backend/routers/ingest.py:169
if result.is_fraudulent:
    payload = { "id": case.id, "account_id": case.account_id, "amount": case.amount, ... }
    await broadcaster.broadcast({"event": "new_case", "case": payload})        # live to the UI
    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, emailer.send_fraud_alert, payload)              # email
    loop.run_in_executor(None, emailer.send_webhook_alert, payload)           # webhook
    loop.run_in_executor(None, callbacks.post_event, "case.flagged", callbacks.case_payload(case))
return _verdict(case)   # push callers also get the verdict back synchronously
```

The journey is complete: a raw row became a normalized transaction, was scored against its own account's history by a chain of deterministic engines, checked against the sanctions lists, explained in plain English, and durably recorded as a case an officer can act on.

---

## The properties that make it defensible

These are not aspirations — each is visible in the code above:

1. **Deterministic core.** Every decision — risk, CTR, SAR, sanctions — is computed in `evaluate()` and the engines it calls. The LLM is opt-in and touches only prose (`analyzer.py:939`). An AI outage can never change a verdict or drop a transaction.
2. **Explainable by construction.** Risk is accumulated as `{score, reason}` components; reasons are templated deterministically; sanctions matching is transparent by design. Nothing asks the officer to trust a number they can't trace.
3. **Never-miss over never-stall.** The poller advances its checkpoint only after a case is committed, and re-raises transient errors to retry rather than skip (`poller.py:185`, `:190`).
4. **Idempotent.** A unique `(source_table, source_txn_id)` constraint plus a pre-check guard mean replays and races can't create duplicate cases (`models.py:21`, `poller.py:95`).
5. **Standards-anchored.** The thresholds carry their regulatory citations in the source (31 CFR 1010.311 for CTR, 31 CFR 1020.320 for SAR).
6. **Tunable and governed.** Detection parameters are overridable live from the settings API, and `snapshot_rules()` / `restore_rules()` capture and restore them around backtests (`analyzer.py:101`, `:130`).
7. **Honest about scope.** Boundaries are documented, not hidden — e.g. the sanctions module states plainly that the OFAC 50%-ownership rule is out of scope because FMS holds no beneficial-ownership data (`sanctions.py:23`).

---

## Appendix — module map

| File | Role in the pipeline |
|---|---|
| `backend/adapters/base.py` | `NormalizedTransaction` + the adapter interface every DB vendor implements |
| `backend/adapters/{mysql,postgres,oracle,mssql}.py` | Vendor-specific readers |
| `backend/routers/ingest.py` | Push API, `run_ingest` orchestration, case creation, alerting |
| `backend/services/poller.py` | Pull-mode loop, checkpointing, idempotency, orchestration |
| `backend/services/analyzer.py` | The engines: thresholds, profiler, risk scorer, CTR, SAR, batch, reasons, summary; `evaluate()` + `analyze()` |
| `backend/services/sanctions.py` | OFAC SDN / Consolidated / PEP / bring-your-own screening |
| `backend/models.py` | `FraudCase`, `IngestedTransaction`, `ProcessingState` persistence |
| `backend/services/{broadcaster,emailer,callbacks}.py` | Real-time and outbound alerting |

*Every excerpt above is quoted from the FMS source at the line reference given. Open the file and read the surrounding function — that is the surest way to know this system is yours.*
