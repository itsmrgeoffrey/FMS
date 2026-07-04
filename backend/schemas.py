from datetime import datetime
from typing import Any
from pydantic import BaseModel


class CaseActionOut(BaseModel):
    id: int
    case_id: str
    action: str
    actor: str
    note: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class FraudCaseOut(BaseModel):
    id: str
    source_table: str
    source_txn_id: str
    account_id: str
    amount: float
    direction: str
    timestamp: datetime
    counterparty_account: str | None
    counterparty_name: str | None
    channel: str | None
    currency: str
    reference: str | None
    risk_score: int | None
    ctr_required: bool
    ctr_reason: str | None
    sar_recommended: bool = False
    sar_reason: str | None = None
    sanctions_hit: bool = False
    sanctions_detail: str | None = None
    confidence: str
    fraud_type: str | None
    reasons: list[str]
    ai_summary: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    actions: list[CaseActionOut] = []

    model_config = {"from_attributes": True}


class FraudCaseListItem(BaseModel):
    id: str
    source_table: str
    account_id: str
    amount: float
    direction: str
    timestamp: datetime
    counterparty_name: str | None
    channel: str | None
    currency: str
    reference: str | None
    risk_score: int | None
    ctr_required: bool
    sar_recommended: bool = False
    sanctions_hit: bool = False
    confidence: str
    fraud_type: str | None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class CaseActionCreate(BaseModel):
    action: str  # DISMISSED / CONFIRMED / ESCALATED / REVIEW / NOTE_ADDED
    note: str | None = None
    actor: str | None = None  # who performed the action; falls back to X-Actor header / "analyst"


class StatsOut(BaseModel):
    flagged_today: int
    high_confidence: int
    pending_review: int
    confirmed_fraud: int
    dismissed_today: int


class HealthOut(BaseModel):
    status: str
    bank_db_connected: bool
    poller_running: bool
    last_poll_at: datetime | None
    last_error: str | None = None


class CasesPage(BaseModel):
    items: list[FraudCaseListItem]
    total: int
    page: int
    limit: int
