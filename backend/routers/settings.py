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

import yaml
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from backend.auth import require_user
from backend.config import ROOT, bank_config, settings
from backend.models import User
from backend.routers import audit

log = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(require_user)])

_YAML_PATH = ROOT / "bank_config.yaml"
_ENV_PATH = ROOT / ".env"

# The normalized transaction fields a bank table can map columns onto.
MAPPABLE_FIELDS = [
    "id", "account_id", "amount", "timestamp", "counterparty_account",
    "counterparty_name", "channel", "currency", "reference", "status", "batch_id",
]


class DatabaseSettings(BaseModel):
    type: str | None = None
    host: str | None = None
    port: int | None = None
    user: str | None = None
    password: str | None = None          # empty = unchanged
    database: str | None = None
    trusted_connection: bool | None = None


class MonitoringSettings(BaseModel):
    poll_interval_seconds: int | None = None
    history_days: int | None = None


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
    return {
        "database": {
            "type": db.get("type", "mysql"),
            "host": db.get("host", ""),
            "port": db.get("port", 3306),
            "user": db.get("user", ""),
            "password_set": bool(db.get("password")),
            "database": db.get("database", ""),
            "trusted_connection": bool(db.get("trusted_connection", False)),
        },
        "tables": bank_config.get("tables", {}),
        "mappable_fields": MAPPABLE_FIELDS,
        "monitoring": {
            "poll_interval_seconds": int(mon.get("poll_interval_seconds", 30)),
            "history_days": int(mon.get("history_days", 90)),
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


@router.put("")
async def update_settings(body: SettingsUpdate, request: Request, user: User = Depends(require_user)):
    restart_required = False
    data = _read_yaml()

    if body.database is not None:
        db = data.setdefault("database", {})
        for field in ("type", "host", "port", "user", "database", "trusted_connection"):
            value = getattr(body.database, field)
            if value is not None:
                db[field] = value
        if body.database.password:  # empty = keep existing
            db["password"] = body.database.password
        restart_required = True

    if body.tables is not None:
        data["tables"] = body.tables
        restart_required = True

    if body.monitoring is not None:
        mon = data.setdefault("monitoring", {})
        if body.monitoring.poll_interval_seconds is not None:
            mon["poll_interval_seconds"] = max(5, int(body.monitoring.poll_interval_seconds))
        if body.monitoring.history_days is not None:
            mon["history_days"] = max(1, int(body.monitoring.history_days))
        # Applies live — the poller re-reads monitoring settings every cycle.
        bank_config["monitoring"] = dict(mon)

    if body.institution is not None:
        inst = data.setdefault("institution", {})
        for field in ("name", "ein", "address", "city", "state", "zip", "primary_regulator"):
            value = getattr(body.institution, field)
            if value is not None:
                inst[field] = value
        # Applies live — FinCEN worksheets read institution at request time.
        bank_config["institution"] = dict(inst)

    if body.database is not None or body.tables is not None or body.monitoring is not None or body.institution is not None:
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

    sections = [k for k in ("database", "tables", "monitoring", "institution", "alerts", "llm", "security")
                if getattr(body, k) is not None]
    await audit.record(
        user.username, "SETTINGS_UPDATED",
        detail=", ".join(sections) or None, request=request,
    )
    log.info(f"Settings updated by {user.username} (restart_required={restart_required})")
    return {"saved": True, "restart_required": restart_required}
