import uuid
from datetime import date, datetime
from sqlalchemy import String, Float, Date, DateTime, Text, Integer, ForeignKey, JSON, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


# String columns carry explicit lengths so the schema is portable to servers
# that require bounded key/indexed columns (e.g. SQL Server). SQLite ignores the
# lengths, so this is safe across both.


class FraudCase(Base):
    __tablename__ = "fraud_cases"
    # A given source transaction must only ever produce one case — guards against
    # duplicate cases on poller replay/crash-recovery.
    __table_args__ = (
        UniqueConstraint("source_table", "source_txn_id", name="uq_case_source_txn"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_table: Mapped[str] = mapped_column(String(20))          # "inward" or "outward"
    source_txn_id: Mapped[str] = mapped_column(String(128))
    account_id: Mapped[str] = mapped_column(String(64), index=True)
    amount: Mapped[float] = mapped_column(Float)
    direction: Mapped[str] = mapped_column(String(10))             # INWARD / OUTWARD
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    counterparty_account: Mapped[str | None] = mapped_column(String(64), nullable=True)
    counterparty_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(40), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Analysis
    risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ctr_required: Mapped[bool] = mapped_column(Boolean, default=False)
    ctr_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    sar_recommended: Mapped[bool] = mapped_column(Boolean, default=False)
    sar_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    sanctions_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    sanctions_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[str] = mapped_column(String(10))            # HIGH / MEDIUM / LOW
    fraud_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # case management
    status: Mapped[str] = mapped_column(String(30), default="OPEN", index=True)
    assigned_to: Mapped[str | None] = mapped_column(String(150), nullable=True, index=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_level: Mapped[str] = mapped_column(String(20), default="STANDARD", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    actions: Mapped[list["CaseAction"]] = relationship(
        "CaseAction", back_populates="case", order_by="CaseAction.created_at"
    )
    decisions: Mapped[list["CaseDecision"]] = relationship(
        "CaseDecision", back_populates="case", order_by="CaseDecision.requested_at", lazy="selectin"
    )
    processing_record: Mapped["TransactionProcessing | None"] = relationship(lazy="selectin", uselist=False)

    @property
    def assessment(self):
        return self.processing_record.assessment if self.processing_record else {
            "version": "legacy", "regulatory_status": "REASSESSMENT_REQUIRED",
            "screening_status": "LEGACY_UNVERIFIED", "reporting_status": "NOT_ASSESSED"}

    @property
    def pending_decision(self):
        return next((decision for decision in reversed(self.decisions) if decision.status == "pending"), None)


class TransactionProcessing(Base):
    __tablename__ = "transaction_processing"
    __table_args__ = (UniqueConstraint("source_table", "source_txn_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_table: Mapped[str] = mapped_column(String(20))
    source_txn_id: Mapped[str] = mapped_column(String(128))
    account_id: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    case_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("fraud_cases.id"), nullable=True, unique=True)
    assessment: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    event: Mapped[str] = mapped_column(String(40))
    channel: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict] = mapped_column(JSON)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class CashActivity(Base):
    """Indexed party/day lookup into exact processing snapshots."""
    __tablename__ = "cash_activity"
    processing_id: Mapped[str] = mapped_column(String(36), ForeignKey("transaction_processing.id"), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), index=True)
    account_holder_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    conductor_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    business_date: Mapped[str] = mapped_column(String(10), index=True)
    currency: Mapped[str] = mapped_column(String(10))
    direction: Mapped[str] = mapped_column(String(10))
    timestamp: Mapped[datetime] = mapped_column(DateTime)


class CtrExemption(Base):
    __tablename__ = "ctr_exemptions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    subject_id: Mapped[str] = mapped_column(String(64), index=True)
    subject_name: Mapped[str] = mapped_column(String(200))
    exemption_type: Mapped[str] = mapped_column(String(40))
    account_ids: Mapped[list] = mapped_column(JSON)
    effective_from: Mapped[date] = mapped_column(Date)
    expires_on: Mapped[date] = mapped_column(Date)
    reviewed_on: Mapped[date] = mapped_column(Date)
    review_due: Mapped[date] = mapped_column(Date)
    eligibility_basis: Mapped[str] = mapped_column(Text)
    evidence_reference: Mapped[str] = mapped_column(String(255))
    designation_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="ACTIVE", index=True)
    created_by: Mapped[str] = mapped_column(String(150))
    approved_by: Mapped[str] = mapped_column(String(150))
    approved_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    revoked_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class RevokedSession(Base):
    __tablename__ = "revoked_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class CaseAction(Base):
    __tablename__ = "case_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("fraud_cases.id"), index=True)
    action: Mapped[str] = mapped_column(String(30))  # OPENED/DISMISSED/CONFIRMED/ESCALATED/REVIEW/NOTE_ADDED
    actor: Mapped[str] = mapped_column(String(150), default="analyst")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    case: Mapped["FraudCase"] = relationship("FraudCase", back_populates="actions")


class CaseDecision(Base):
    """A proposed final disposition awaiting an independent checker."""
    __tablename__ = "case_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("fraud_cases.id"), index=True)
    proposed_action: Mapped[str] = mapped_column(String(20))  # CONFIRMED / DISMISSED
    rationale: Mapped[str] = mapped_column(Text)
    requested_by: Mapped[str] = mapped_column(String(150), index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)
    decided_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    case: Mapped["FraudCase"] = relationship("FraudCase", back_populates="decisions")


class CaseBatch(Base):
    """Durable server-side bulk work; case IDs are snapshotted at submission."""
    __tablename__ = "case_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    action: Mapped[str] = mapped_column(String(20))
    case_ids: Mapped[list] = mapped_column(JSON, default=list)
    rationale: Mapped[str] = mapped_column(Text)
    requested_by: Mapped[str] = mapped_column(String(150), index=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    succeeded: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(150), unique=True, index=True, nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="analyst")  # admin / analyst / approver / viewer
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Set when an admin issues a temporary password. Until the user chooses their
    # own, the temp credential is known to whoever issued (and emailed) it, so the
    # app blocks normal use until it is replaced.
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(150), index=True)
    action: Mapped[str] = mapped_column(String(50), index=True)   # LOGIN / CASE_DISMISSED / SETTINGS_UPDATED ...
    target: Mapped[str | None] = mapped_column(String(150), nullable=True)   # case id / resource affected
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class PendingApproval(Base):
    """A sensitive administrative change awaiting a second admin's approval
    (dual control / maker-checker). The requesting admin is the *maker*; a
    different admin must approve (*checker*) before the change executes."""
    __tablename__ = "pending_approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    action: Mapped[str] = mapped_column(String(40), index=True)    # USER_CREATE / USER_SET_ROLE / ...
    payload: Mapped[str] = mapped_column(Text)                      # JSON args for the executor
    target: Mapped[str | None] = mapped_column(String(150), nullable=True)   # affected user/resource
    summary: Mapped[str] = mapped_column(String(300))               # human-readable description
    requested_by: Mapped[str] = mapped_column(String(150), index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)  # pending/approved/rejected/cancelled
    decided_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class RiskAssessment(Base):
    """Versioned institutional ML/TF risk assessment — the documented artifact
    FinCEN's 2026 AML/CFT Program rule proposal would require. FMS structures the
    assessment (category grid, National-Priorities checklist) and pre-populates
    the activity snapshot from its own data ('reports filed' consideration);
    the RATINGS and judgments are the institution's — FMS never auto-rates."""
    __tablename__ = "risk_assessments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    version: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(10), default="DRAFT", index=True)   # DRAFT / FINAL
    title: Mapped[str] = mapped_column(String(200), default="Institutional ML/TF Risk Assessment")
    categories: Mapped[list] = mapped_column(JSON, default=list)       # rows: area/item/inherent/controls/residual/notes
    priorities: Mapped[list] = mapped_column(JSON, default=list)       # National Priorities checklist
    activity_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    overall_rating: Mapped[str | None] = mapped_column(String(10), nullable=True)  # LOW/MODERATE/HIGH (officer's call)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(150))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    finalized_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RuleChange(Base):
    """Tuning log: one row per detection-parameter change, with before/after
    values, who made it, and the documented rationale — the FFIEC expects
    thresholds to be 'documented and periodically reviewed', and this table is
    that evidence. Optionally carries the backtest summary the admin ran before
    saving (predicted effect, to compare against actual)."""
    __tablename__ = "rule_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    changed_by: Mapped[str] = mapped_column(String(150), index=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    old_values: Mapped[dict] = mapped_column(JSON, default=dict)
    new_values: Mapped[dict] = mapped_column(JSON, default=dict)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    backtest: Mapped[dict | None] = mapped_column(JSON, nullable=True)


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
    direction: Mapped[str] = mapped_column(String(10))
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    counterparty_account: Mapped[str | None] = mapped_column(String(64), nullable=True)
    counterparty_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(40), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    account_holder_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ProcessingState(Base):
    __tablename__ = "processing_state"

    table_key: Mapped[str] = mapped_column(String(50), primary_key=True)
    last_processed_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class UsageDaily(Base):
    """Aggregate daily usage counter for the public metrics/status page.

    Privacy-preserving by design: a per-day count of HTTP requests served, with
    NO user, device, IP, or session identifiers stored. (Transactions, alerts,
    and logins are counted directly from their own tables; this records only
    request volume, which isn't otherwise persisted.) create_all() builds this
    table on startup, so no migration is needed on existing deployments."""
    __tablename__ = "usage_daily"

    day: Mapped[str] = mapped_column(String(10), primary_key=True)  # YYYY-MM-DD (UTC)
    requests: Mapped[int] = mapped_column(Integer, default=0)
