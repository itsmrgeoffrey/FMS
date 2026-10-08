"""Runtime configuration API — powers the Settings page in the UI.

Reads and persists the two config surfaces (bank_config.yaml and .env) so an
operator can configure FMS without editing files:

- **Live-applied on save:** monitoring cadence, institution details (FinCEN
  worksheets), alert email settings, LLM settings, API key. These are read from
  shared state at use-time, so mutating that state applies immediately.
- **Restart required:** database connection and table mappings. The adapter and
  poller bind these at startup; the API persists them and tells the UI a
  restart is needed rather than pretending otherwise.

Secrets (passwords, API keys) are never returned — GET reports only whether
each is set. On save, empty secret fields mean "keep the current value".
"""
import logging
import os
from datetime import datetime
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import require_admin
from backend.config import APP_VERSION, ENVIRONMENT, ROOT, bank_config, settings
from backend.database import get_db
from backend.models import PendingApproval, User
from backend.routers import audit
from backend.services import dual_control, poller
from backend.services.installation import OperatingProfile

log = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(require_admin)])

# Persist to the SAME files this process loaded its config from — the
# environment selectors (FMS_BANK_CONFIG / FMS_ENV_FILE, used by the prod/ and
# test/ environments) must be honored here too, or an admin's settings change
# would write to the root files and silently vanish on restart.
_YAML_PATH = Path(os.getenv("FMS_BANK_CONFIG", "").strip() or (ROOT / "bank_config.yaml"))
_ENV_PATH = Path(os.getenv("FMS_ENV_FILE", "").strip() or (ROOT / ".env"))

# The normalized transaction fields a bank table can map columns onto.
MAPPABLE_FIELDS = [
    "id", "account_id", "amount", "timestamp", "counterparty_account",
    "counterparty_name", "channel", "currency", "reference", "status", "batch_id",
    "account_holder_name", "account_holder_id", "is_cash", "business_date",
    "transaction_instrument", "branch_id", "location_id", "conductor_id", "conductor_name",
]

_DATABASE_FIELDS = (
    "type", "host", "port", "user", "database", "trusted_connection",
    "encrypt", "trust_server_certificate",
)


def _public_database(db: dict) -> dict:
    return {
        "type": db.get("type", "mysql"),
        "host": db.get("host", ""),
        "port": db.get("port", 3306),
        "user": db.get("user", ""),
        "password_set": bool(db.get("password")),
        "database": db.get("database", ""),
        "trusted_connection": bool(db.get("trusted_connection", False)),
        "encrypt": bool(db.get("encrypt", False)),
        "trust_server_certificate": bool(db.get("trust_server_certificate", True)),
    }


def _merge_database(existing: dict, incoming: dict) -> dict:
    merged = {field: incoming[field] for field in _DATABASE_FIELDS if field in incoming}
    password = incoming.get("password") or existing.get("password")
    if password:
        merged["password"] = password
    return merged


class DatabaseSettings(BaseModel):
    type: str | None = None
    host: str | None = None
    port: int | None = None
    user: str | None = None
    password: str | None = None          # empty = unchanged
    database: str | None = None
    trusted_connection: bool | None = None
    encrypt: bool | None = None                  # TLS
    trust_server_certificate: bool | None = None


class MonitoringSettings(BaseModel):
    poll_interval_seconds: int | None = None
    history_days: int | None = None
    mode: str | None = None            # "api" (push only, no bank DB) or "poll"


class IntegrationsSettings(BaseModel):
    callback_url: str | None = None
    callback_secret: str | None = None  # empty = unchanged


class DirectorySettings(BaseModel):
    enabled: bool | None = None
    server_uri: str | None = None
    start_tls: bool | None = None
    bind_user_template: str | None = None
    base_dn: str | None = None
    user_search: str | None = None
    email_domain: str | None = None
    default_role: str | None = None
    group_role_map: dict | None = None


class InstitutionSettings(BaseModel):
    name: str | None = None
    ein: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    primary_regulator: str | None = None


class AlertSettings(BaseModel):
    gmail_user: str | None = None
    gmail_app_password: str | None = None  # empty = unchanged
    alert_email: str | None = None


class LlmSettings(BaseModel):
    groq_api_key: str | None = None        # empty = unchanged
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None             # empty = unchanged


class SecuritySettings(BaseModel):
    fms_api_key: str | None = None         # empty = unchanged


class SettingsUpdate(BaseModel):
    database: DatabaseSettings | None = None
    tables: dict | None = None             # full tables mapping as edited
    rules: dict | None = None              # detection-rule overrides (live-applied)
    rules_rationale: str | None = None     # documented reason for the rule change (tuning log)
    rules_backtest: dict | None = None     # legacy client field; never trusted as evidence
    rules_base_version: str | None = None
    rules_allow_empty_history: bool = False
    operating_profile: OperatingProfile | None = None
    configuration_revision: str | None = None
    profile_rationale: str | None = None
    integrations: IntegrationsSettings | None = None
    directory: DirectorySettings | None = None
    monitoring: MonitoringSettings | None = None
    institution: InstitutionSettings | None = None
    alerts: AlertSettings | None = None
    llm: LlmSettings | None = None
    security: SecuritySettings | None = None


def _read_yaml() -> dict:
    if _YAML_PATH.exists():
        with open(_YAML_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def _write_yaml(data: dict) -> None:
    with open(_YAML_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def _update_env(updates: dict[str, str]) -> None:
    """Update or append KEY=value lines in .env, preserving everything else."""
    lines = _ENV_PATH.read_text(encoding="utf-8").splitlines() if _ENV_PATH.exists() else []
    done: set[str] = set()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if "=" in stripped and not stripped.startswith("#"):
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                out.append(f"{key}={updates[key]}")
                done.add(key)
                continue
        out.append(line)
    for key, value in updates.items():
        if key not in done:
            out.append(f"{key}={value}")
    _ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")


@router.get("")
async def get_settings():
    db = bank_config.get("database", {}) or {}
    mon = bank_config.get("monitoring", {}) or {}
    inst = bank_config.get("institution", {}) or {}
    _dir = bank_config.get("directory", {}) or {}
    public_tables = {}
    for key, config in (bank_config.get("tables", {}) or {}).items():
        public_config = {k: v for k, v in config.items() if k != "database"}
        if config.get("database"):
            public_config["database"] = _public_database(config["database"])
        public_tables[key] = public_config
    return {
        "database": _public_database(db),
        "tables": public_tables,
        "mappable_fields": MAPPABLE_FIELDS,
        "monitoring": {
            "poll_interval_seconds": int(mon.get("poll_interval_seconds", 30)),
            "history_days": int(mon.get("history_days", 90)),
            "mode": mon.get("mode", "poll"),
        },
        "integrations": {
            "callback_url": (bank_config.get("integrations", {}) or {}).get("callback_url", ""),
            "callback_secret_set": bool((bank_config.get("integrations", {}) or {}).get("callback_secret")),
        },
        "directory": {
            "enabled": bool(_dir.get("enabled", False)),
            "server_uri": _dir.get("server_uri", ""),
            "start_tls": bool(_dir.get("start_tls", False)),
            "bind_user_template": _dir.get("bind_user_template", ""),
            "base_dn": _dir.get("base_dn", ""),
            "user_search": _dir.get("user_search", "(sAMAccountName={username})"),
            "email_domain": _dir.get("email_domain", ""),
            "default_role": _dir.get("default_role", "viewer"),
            "group_role_map": _dir.get("group_role_map", {}) or {},
        },
        "institution": {
            "name": inst.get("name", ""),
            "ein": inst.get("ein", ""),
            "address": inst.get("address", ""),
            "city": inst.get("city", ""),
            "state": inst.get("state", ""),
            "zip": inst.get("zip", ""),
            "primary_regulator": inst.get("primary_regulator", ""),
        },
        "alerts": {
            "gmail_user": settings.gmail_user,
            "gmail_app_password_set": bool(settings.gmail_app_password),
            "alert_email": settings.alert_email,
        },
        "llm": {
            "groq_api_key_set": bool(settings.groq_api_key),
            "base_url": settings.llm_base_url,
            "model": settings.llm_model,
            "api_key_set": bool(settings.llm_api_key),
        },
        "security": {
            "api_key_set": bool(settings.fms_api_key),
        },
    }


@router.post("/test-connection")
async def test_connection(
    source: str = Query("shared", pattern="^(shared|inward|outward)$"),
    user: User = Depends(require_admin),
):
    """Attempt a connection to the configured bank database and report status."""
    if source != "shared" and source not in (bank_config.get("tables", {}) or {}):
        raise HTTPException(404, f"No '{source}' transaction source is configured")
    try:
        adapter = poller.get_adapter(source)
        connected = await adapter.is_connected()
        if not connected:
            await adapter.connect()
            connected = await adapter.is_connected()
        if connected:
            db_config = bank_config.get("database", {}) if source == "shared" else poller.source_database(source)
            return {"connected": True, "message": "Connection successful.",
                    "source": source, "db_type": db_config.get("type", "")}
        return {"connected": False, "message": "Could not establish a connection."}
    except Exception as e:
        return {"connected": False, "message": f"Connection failed: {e}"}


@router.post("/test-directory")
async def test_directory(user: User = Depends(require_admin)):
    """Check the configured LDAP/AD server is reachable."""
    from backend.services import ldap_auth
    ok, message = ldap_auth.test_connection()
    return {"connected": ok, "message": message, "enabled": ldap_auth.is_enabled()}


@router.get("/system-info")
async def system_info(user: User = Depends(require_admin)):
    from backend.services import sanctions

    api_mode = bank_config.get("monitoring", {}).get("mode", "poll") == "api"
    # "database_connected" previously reported poller.is_running(), which is a
    # flag set once at startup and never cleared — so it read "connected" in
    # API-push mode (where there is no bank database at all) and stayed
    # "connected" while the bank DB was down.
    #
    # Report the poller's LAST OBSERVED state instead of probing. A status
    # endpoint must not open a connection to the institution's database as a
    # side effect of someone loading the Administration page — that would send
    # traffic to the bank host on every page view, and an admin refreshing would
    # hammer it. The poller already records what it saw on its last cycle.
    bank_connected = None if api_mode else poller.last_connect_ok()

    # The write path exists but is gated to development (see routers/transactions.py),
    # so report the real state rather than asserting True unconditionally.
    write_path_enabled = ENVIRONMENT.lower() == "development"

    return {
        "app_version": APP_VERSION,
        "environment": ENVIRONMENT,
        "ingestion_mode": "api" if api_mode else "poll",
        "database_connected": bank_connected,
        "source_connections": poller.connection_statuses(),
        "poller_running": poller.is_running(),
        "poller_last_error": poller.last_error(),
        "database_type": bank_config.get("database", {}).get("type", ""),
        # True in every normal deployment; False only when the development-only
        # demo injection endpoint is reachable.
        "read_only": not write_path_enabled,
        "demo_write_endpoint_enabled": write_path_enabled,
        "audit_logging": True,
        "sanctions_screening": sanctions.status(),
        "encryption": {
            "auth_tokens_signed": True,
            "db_tls": bool(bank_config.get("database", {}).get("encrypt", False)),
        },
        "server_time": datetime.utcnow().isoformat() + "Z",
        "last_poll_at": poller.last_poll_at().isoformat() + "Z" if poller.last_poll_at() else None,
    }


@router.get("/installation")
async def get_installation(db: AsyncSession = Depends(get_db)):
    from backend.services.installation import inspect
    return await inspect(db)


@dual_control.register("SETTINGS_UPDATE")
async def _exec_settings_update(db: AsyncSession, payload: dict, actor: str, request: Request | None,
                                *, approval: PendingApproval | None = None) -> dict:
    body = SettingsUpdate(**payload)
    if dual_control.requires_independent_approval("SETTINGS_UPDATE", payload) and approval is None:
        raise HTTPException(403, "Detection configuration requires independent approval.")
    if body.operating_profile is not None:
        from backend.services.rule_governance import apply_profile
        return await apply_profile(db, body.operating_profile.model_dump(), body.profile_rationale,
                                   body.configuration_revision, actor, approval=approval)
    if body.rules is not None:
        from backend.services.rule_governance import apply_change
        return await apply_change(db, body.rules, body.rules_rationale, body.rules_base_version,
                                  actor, body.rules_allow_empty_history, approval=approval)
    return await _apply_settings(body, actor, request)


@router.put("")
async def update_settings(
    body: SettingsUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Rules and operating profiles always require independent approval."""
    sections = [k for k in ("database", "tables", "rules", "monitoring", "institution",
                            "alerts", "llm", "security", "integrations", "directory", "operating_profile")
                if getattr(body, k) is not None]
    if not sections:
        return {"saved": False, "restart_required": False}
    if body.operating_profile is not None:
        from backend.services.rule_governance import revision
        if sections != ["operating_profile"]:
            raise HTTPException(422, "Save the operating profile separately from other settings.")
        if not (body.profile_rationale or "").strip():
            raise HTTPException(422, "A reason for the profile change is required.")
        if body.configuration_revision != revision():
            raise HTTPException(409, "Configuration changed. Reload the installation profile.")
    if body.rules is not None:
        from backend.services import analyzer
        from backend.services.rule_governance import revision
        if sections != ["rules"]:
            raise HTTPException(422, "Save detection rules separately from other settings.")
        if not (body.rules_rationale or "").strip():
            raise HTTPException(422, "A reason for the rule change is required.")
        if body.rules_base_version != revision():
            raise HTTPException(409, "Rules changed or no revision was supplied. Reload the rule settings.")
        try:
            analyzer.validate_rule_overrides(body.rules)
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
    payload = body.model_dump(exclude_none=True)
    if body.rules is not None:
        from backend.services.analyzer import snapshot_rules
        payload["configuration_before"] = snapshot_rules()
    elif body.operating_profile is not None:
        from backend.services.installation import profile
        payload["configuration_before"] = profile()
    return await dual_control.submit_or_execute(
        db, request, user,
        action="SETTINGS_UPDATE",
        payload=payload,
        summary="Update settings: " + ", ".join(sections),
        target="settings",
    )


async def _apply_settings(body: SettingsUpdate, actor: str, request: Request | None) -> dict:
    if body.rules is not None:
        raise HTTPException(422, "Detection rules must use the versioned rule-change path.")
    restart_required = False
    data = _read_yaml()

    db_changes: list[str] = []
    if body.database is not None:
        db = data.setdefault("database", {})
        # Track old->new for non-secret fields for the activity log.
        for field in ("type", "host", "port", "user", "database", "trusted_connection",
                      "encrypt", "trust_server_certificate"):
            value = getattr(body.database, field)
            if value is not None and db.get(field) != value:
                db_changes.append(f"{field}: {db.get(field)!r} → {value!r}")
                db[field] = value
        if body.database.password:  # empty = keep existing
            db["password"] = body.database.password
            db_changes.append("password: (changed)")
        restart_required = True

    if body.tables is not None:
        existing_tables = data.get("tables", {}) or {}
        next_tables = {}
        for key, config in body.tables.items():
            next_config = {k: v for k, v in config.items() if k != "database"}
            if config.get("database") is not None:
                existing_database = (existing_tables.get(key, {}) or {}).get("database", {}) or {}
                next_config["database"] = _merge_database(existing_database, config["database"])
            next_tables[key] = next_config
        data["tables"] = next_tables
        restart_required = True

    if body.monitoring is not None:
        mon = data.setdefault("monitoring", {})
        if body.monitoring.poll_interval_seconds is not None:
            mon["poll_interval_seconds"] = max(5, int(body.monitoring.poll_interval_seconds))
        if body.monitoring.history_days is not None:
            mon["history_days"] = max(1, int(body.monitoring.history_days))
        if body.monitoring.mode in ("api", "poll"):
            mon["mode"] = body.monitoring.mode
        # Applies live — the poller re-reads monitoring settings every cycle.
        bank_config["monitoring"] = dict(mon)

    if body.integrations is not None:
        integ = data.setdefault("integrations", {})
        if body.integrations.callback_url is not None:
            integ["callback_url"] = body.integrations.callback_url.strip()
        if body.integrations.callback_secret:  # empty = keep existing
            integ["callback_secret"] = body.integrations.callback_secret
        # Applies live — callbacks read config at send time.
        bank_config["integrations"] = dict(integ)

    if body.directory is not None:
        d = data.setdefault("directory", {})
        for field in ("enabled", "server_uri", "start_tls", "bind_user_template",
                      "base_dn", "user_search", "email_domain", "default_role", "group_role_map"):
            value = getattr(body.directory, field)
            if value is not None:
                d[field] = value
        # Applies live — the login flow reads directory config per request.
        bank_config["directory"] = dict(d)

    if body.institution is not None:
        inst = data.setdefault("institution", {})
        for field in ("name", "ein", "address", "city", "state", "zip", "primary_regulator"):
            value = getattr(body.institution, field)
            if value is not None:
                inst[field] = value
        # Applies live — FinCEN worksheets read institution at request time.
        bank_config["institution"] = dict(inst)

    if any(x is not None for x in (body.database, body.tables, body.monitoring, body.institution, body.rules, body.integrations, body.directory)):
        _write_yaml(data)

    env_updates: dict[str, str] = {}
    if body.alerts is not None:
        if body.alerts.gmail_user is not None:
            settings.gmail_user = body.alerts.gmail_user
            env_updates["GMAIL_USER"] = body.alerts.gmail_user
        if body.alerts.gmail_app_password:
            settings.gmail_app_password = body.alerts.gmail_app_password
            env_updates["GMAIL_APP_PASSWORD"] = body.alerts.gmail_app_password
        if body.alerts.alert_email is not None:
            settings.alert_email = body.alerts.alert_email
            env_updates["ALERT_EMAIL"] = body.alerts.alert_email

    if body.llm is not None:
        if body.llm.groq_api_key:
            settings.groq_api_key = body.llm.groq_api_key
            env_updates["GROQ_API_KEY"] = body.llm.groq_api_key
            # Force the lazily-built Groq client to rebuild with the new key.
            from backend.services import analyzer
            analyzer._client = None
        if body.llm.base_url is not None:
            settings.llm_base_url = body.llm.base_url
            env_updates["LLM_BASE_URL"] = body.llm.base_url
        if body.llm.model is not None:
            settings.llm_model = body.llm.model
            env_updates["LLM_MODEL"] = body.llm.model
        if body.llm.api_key:
            settings.llm_api_key = body.llm.api_key
            env_updates["LLM_API_KEY"] = body.llm.api_key

    if body.security is not None and body.security.fms_api_key is not None:
        # Applies live — auth reads settings.fms_api_key per request. Note: setting
        # this locks the API immediately, including this settings page.
        settings.fms_api_key = body.security.fms_api_key
        env_updates["FMS_API_KEY"] = body.security.fms_api_key

    if env_updates:
        _update_env(env_updates)

    sections = [k for k in ("database", "tables", "rules", "monitoring", "institution", "alerts", "llm", "security", "integrations", "directory")
                if getattr(body, k) is not None]
    detail = ", ".join(sections) or None
    if db_changes:
        detail = f"{detail} [{'; '.join(db_changes)}]"
    await audit.record(actor, "SETTINGS_UPDATED", detail=detail, request=request)
    log.info(f"Settings updated by {actor} (restart_required={restart_required})")
    return {"saved": True, "restart_required": restart_required}
