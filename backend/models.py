import uuid
from datetime import datetime
from sqlalchemy import String, Float, DateTime, Text, Integer, ForeignKey, JSON, Boolean, UniqueConstraint
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    actions: Mapped[list["CaseAction"]] = relationship(
        "CaseAction", back_populates="case", order_by="CaseAction.created_at"
    )


class CaseAction(Base):
    __tablename__ = "case_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("fraud_cases.id"), index=True)
    action: Mapped[str] = mapped_column(String(30))  # OPENED/DISMISSED/CONFIRMED/ESCALATED/REVIEW/NOTE_ADDED
    actor: Mapped[str] = mapped_column(String(150), default="analyst")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    case: Mapped["FraudCase"] = relationship("FraudCase", back_populates="actions")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(150), unique=True, index=True, nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="analyst")  # admin / analyst / viewer
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
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
