"""Small-installation configuration and explicit capability boundaries."""
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select

from backend.config import bank_config, settings
from backend.models import AuditLog, IngestedTransaction, ProcessingState, TransactionProcessing, User
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
    mode = mon.get("mode", "poll")
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
    checkpoints = {row.table_key: row for row in (await db.execute(select(ProcessingState))).scalars()}
    api_count, api_first, api_last = (await db.execute(select(
        func.count(IngestedTransaction.id), func.min(IngestedTransaction.timestamp),
        func.max(IngestedTransaction.timestamp)))).one()
    onboarding = {
        "mode": mode,
        "history_days": int(mon.get("history_days", 90)),
        "required_history_days": required_history,
        "polling_start": "Existing rows at first connection are baseline only, not assessed transactions. Monitoring starts after the highest source ID. An empty source is initialized so its first arrivals are assessed.",
        "cursor_requirement": "Source IDs must be unique, immutable and increasing in database sort order. Lower-ID late inserts and updates to existing rows are not discovered by this poller. Random UUID cursors require an upstream ordered feed or API push.",
        "history_supply": "Database polling reads account history from the mapped source tables within the configured lookback from the current date; this does not create historical assessments. For API push, send historical transactions oldest first with original timestamps and stable IDs before live traffic. Every submission uses normal review and notification processing; there is no silent history-only import.",
        "history_verification": "Stored date ranges and configured windows do not prove completeness. Reconcile counts and amounts by account, currency and day with the source before enabling live traffic. For older backfills, prefer API push: polling history is relative to the current date. Late submissions do not rewrite later assessments.",
        "api_id_convention": "Use <system-prefix>:<original-transaction-id>, for example core:12345 and wallet:12345. Assign each upstream system a stable unique prefix without colons. Keep the full ID within 128 characters and unchanged on retries. Channel is not an ID namespace. Reusing an ID with changed data returns 409; do not create a new ID to bypass it. Existing IDs must not be renamed or resent with a new prefix.",
        "api_history": {"count": api_count, "earliest": api_first, "latest": api_last},
        "checkpoints": [{"table_key": key, "initialized": key in checkpoints,
            "cursor": checkpoints[key].last_processed_id if key in checkpoints else None,
            "updated_at": checkpoints[key].updated_at if key in checkpoints else None}
            for key in bank_config.get("tables", {})],
    }
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
    return {"profile": profile(), "revision": revision(), "checks": checks, "onboarding": onboarding,
            "reporting_scope": "US-bank USD assessment; all other currencies require manual review." if automatic else "Manual reporting assessment; no automatic rules for this institution scope.",
            "capabilities": ["API push or read-only database polling", "Arbitrary transaction channels", "Currency-specific behavioural benchmarks", "Versioned rule changes and stored-data replay", "Human review, dispositions and exports"],
            "boundaries": ["One institution per deployment", "One backend worker and one replica", "Account-level analysis, not verified KYC or ownership analysis", "No payment execution or automatic blocking", "Draft reporting aids, not report submission", "Independent validation and source reconciliation remain institution responsibilities"]}
