"""Small-installation configuration and explicit capability boundaries."""
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select

from backend.config import bank_config, settings
from backend.models import AuditLog, TransactionProcessing, User
from backend.services import analyzer, poller, sanctions


class OperatingProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    regulatory_jurisdiction: str = Field(pattern=r"^[A-Z]{2}$")
    institution_type: Literal["bank", "credit_union", "msb", "fintech", "other"]
    business_timezone: str = Field(max_length=100)

    @field_validator("business_timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Use an IANA timezone such as America/New_York or Africa/Lagos") from exc
        return value


def profile() -> dict:
    return {key: getattr(settings, key) for key in OperatingProfile.model_fields}


def activate(value: dict):
    checked = OperatingProfile(**value)
    for key, item in checked.model_dump().items():
        setattr(settings, key, item)


async def inspect(db):
    from backend.services.rule_governance import revision
    mon = bank_config.get("monitoring", {})
    mode = mon.get("mode", "api")
    st = sanctions.status()
    active_admins = (await db.execute(select(func.count()).select_from(User).where(
        User.role == "admin", User.is_active.is_(True)))).scalar_one()
    failed = (await db.execute(select(func.count()).select_from(TransactionProcessing).where(
        TransactionProcessing.state == "FAILED"))).scalar_one()
    configured = (await db.execute(select(AuditLog.id).where(
        AuditLog.action == "PROFILE_UPDATED").limit(1))).first() is not None
    required_history = max(analyzer.ROLLING_WINDOW_DAYS, (analyzer.SMURFING_WINDOW_HOURS + 23) // 24)
    screening_current = st.get("ok") and not sanctions.needs_refresh(max(24, settings.ofac_refresh_hours * 2))
    screening_detail = st.get("detail") or ("Current sanctions list available; possible matches require human review."
        if screening_current else "Sanctions-list availability or freshness needs attention. Verify and refresh the lists.")
    automatic = settings.regulatory_jurisdiction == "US" and settings.institution_type == "bank"
    checks = [
        {"key": "institution", "label": "Institution identity", "state": "configured" if (bank_config.get("institution", {}).get("name") or "").strip() else "attention", "detail": bank_config.get("institution", {}).get("name") or "Institution name has not been set.", "href": "/settings?tab=system"},
        {"key": "profile", "label": "Operating profile", "state": "configured" if configured else "attention", "detail": "Saved institution scope and business timezone." if configured else "Environment defaults are in use; confirm the installation profile.", "href": "/settings?tab=installation"},
        {"key": "ingestion", "label": "Transaction input", "state": ("configured" if (settings.fms_ingest_api_key or settings.fms_api_key) else "attention") if mode == "api" else ("configured" if poller.last_connect_ok() else "attention"), "detail": "API push mode; source reconciliation still needs operator verification." if mode == "api" else "Database polling; connection status reflects the last poll.", "href": "/settings?tab=system"},
        {"key": "history", "label": "Detection history", "state": "configured" if int(mon.get("history_days", 90)) >= required_history else "attention", "detail": f"Configured history: {mon.get('history_days', 90)} days; current detection windows require at least {required_history} days.", "href": "/settings?tab=system"},
        {"key": "screening", "label": "Sanctions data", "state": "configured" if screening_current else "attention", "detail": screening_detail, "href": "/settings?tab=system"},
        {"key": "recovery", "label": "Processing recovery", "state": "attention" if failed else "configured", "detail": f"{failed} failed processing records.", "href": "/settings?tab=system"},
        {"key": "admins", "label": "Administrative approval", "state": "configured" if active_admins >= 2 else "attention", "detail": f"{active_admins} active administrators. " + ("Rule and profile changes require independent approval." if active_admins >= 2 else "Rule and profile changes remain pending until a different active administrator approves."), "href": "/settings?tab=users"},
        {"key": "operations", "label": "Institution operating controls", "state": "unverified", "detail": "Backup restoration, access security, source completeness and staff procedures require institution verification.", "href": "/settings?tab=system"},
    ]
    return {"profile": profile(), "revision": revision(), "checks": checks,
            "reporting_scope": "US-bank USD assessment; all other currencies require manual review." if automatic else "Manual reporting assessment; no automatic rules for this institution scope.",
            "capabilities": ["API push or read-only database polling", "Arbitrary transaction channels", "Currency-specific behavioural benchmarks", "Versioned rule changes and stored-data replay", "Human review, dispositions and exports"],
            "boundaries": ["One institution per deployment", "One backend worker and one replica", "Account-level analysis, not verified KYC or ownership analysis", "No payment execution or automatic blocking", "Draft reporting aids, not report submission", "Independent validation and source reconciliation remain institution responsibilities"]}
