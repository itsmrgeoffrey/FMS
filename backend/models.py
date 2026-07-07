import uuid
from datetime import datetime
from sqlalchemy import String, Float, DateTime, Text, Integer, ForeignKey, JSON, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class FraudCase(Base):
    __tablename__ = "fraud_cases"
    # A given source transaction must only ever produce one case — guards against
    # duplicate cases on poller replay/crash-recovery.
    __table_args__ = (
        UniqueConstraint("source_table", "source_txn_id", name="uq_case_source_txn"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    source_table: Mapped[str] = mapped_column(String)          # "inward" or "outward"
    source_txn_id: Mapped[str] = mapped_column(String)
    account_id: Mapped[str] = mapped_column(String, index=True)
    amount: Mapped[float] = mapped_column(Float)
    direction: Mapped[str] = mapped_column(String)             # INWARD / OUTWARD
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    counterparty_account: Mapped[str | None] = mapped_column(String, nullable=True)
    counterparty_name: Mapped[str | None] = mapped_column(String, nullable=True)
    channel: Mapped[str | None] = mapped_column(String, nullable=True)
    currency: Mapped[str] = mapped_column(String, default="USD")
    reference: Mapped[str | None] = mapped_column(String, nullable=True)
    # AI analysis
    risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ctr_required: Mapped[bool] = mapped_column(Boolean, default=False)
    ctr_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    sar_recommended: Mapped[bool] = mapped_column(Boolean, default=False)
    sar_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    sanctions_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    sanctions_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[str] = mapped_column(String)            # HIGH / MEDIUM / LOW
    fraud_type: Mapped[str | None] = mapped_column(String, nullable=True)
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # case management
    status: Mapped[str] = mapped_column(String, default="OPEN", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    actions: Mapped[list["CaseAction"]] = relationship(
        "CaseAction", back_populates="case", order_by="CaseAction.created_at"
    )


class CaseAction(Base):
    __tablename__ = "case_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(String, ForeignKey("fraud_cases.id"), index=True)
    action: Mapped[str] = mapped_column(String)  # OPENED/DISMISSED/CONFIRMED/ESCALATED/REVIEW/NOTE_ADDED
    actor: Mapped[str] = mapped_column(String, default="analyst")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    case: Mapped["FraudCase"] = relationship("FraudCase", back_populates="actions")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String, unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String, unique=True, index=True, nullable=True)
    full_name: Mapped[str | None] = mapped_column(String, nullable=True)
    password_hash: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String, default="analyst")  # analyst / admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String, index=True)
    action: Mapped[str] = mapped_column(String, index=True)   # LOGIN / VIEW_CASE / CASE_DISMISSED / SETTINGS_UPDATED ...
    target: Mapped[str | None] = mapped_column(String, nullable=True)   # case id / resource affected
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ProcessingState(Base):
    __tablename__ = "processing_state"

    table_key: Mapped[str] = mapped_column(String, primary_key=True)
    last_processed_id: Mapped[str | None] = mapped_column(String, nullable=True)
    last_processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
