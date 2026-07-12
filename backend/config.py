import logging
import os
import secrets
import yaml
from pathlib import Path
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent

APP_VERSION = "0.1.0"
ENVIRONMENT = os.getenv("FMS_ENV", "development")


class Settings(BaseSettings):
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    # Optional local/self-hosted LLM: any OpenAI-compatible endpoint (e.g. Ollama
    # at http://localhost:11434/v1). When set, it replaces Groq for summaries and
    # no transaction data leaves your infrastructure.
    llm_base_url: str = os.getenv("LLM_BASE_URL", "")
    llm_model: str = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    # AI case summaries are OFF by default. The detection engine is fully
    # deterministic and needs no AI; enabling this only adds a prose summary.
    # With a third-party key (Groq) this sends transaction data off-host, so it
    # is opt-in. A local LLM_BASE_URL keeps data on your infrastructure.
    ai_summaries: str = os.getenv("FMS_AI_SUMMARIES", "off")
    gmail_user: str = os.getenv("GMAIL_USER", "")
    gmail_app_password: str = os.getenv("GMAIL_APP_PASSWORD", "")
    alert_email: str = os.getenv("ALERT_EMAIL", "")
    # Optional webhook for flagged-case alerts (Slack incoming-webhook URLs get
    # Slack-formatted text; anything else receives generic JSON).
    alert_webhook_url: str = os.getenv("ALERT_WEBHOOK_URL", "")
    # Hours between automatic OFAC SDN list refreshes (0 disables).
    ofac_refresh_hours: int = int(os.getenv("FMS_OFAC_REFRESH_HOURS", "24"))
    fms_api_key: str = os.getenv("FMS_API_KEY", "")
    # Key for the push-ingestion API (falls back to FMS_API_KEY if unset).
    fms_ingest_api_key: str = os.getenv("FMS_INGEST_API_KEY", "")
    # Secret used to sign login tokens. Generated once and persisted to .env so
    # issued tokens stay valid across restarts.
    auth_secret: str = os.getenv("FMS_AUTH_SECRET", "")
    # Hours a login token stays valid.
    auth_token_ttl_hours: int = int(os.getenv("FMS_AUTH_TOKEN_TTL_HOURS", "12"))
    # Public signup is disabled after bootstrap unless explicitly enabled.
    allow_signup: bool = os.getenv("FMS_ALLOW_SIGNUP", "false").strip().lower() in ("1", "true", "yes", "on")
    # Required for first-admin bootstrap outside development.
    setup_token: str = os.getenv("FMS_SETUP_TOKEN", "")
    # Only trust X-Forwarded-For when the app is behind a trusted reverse proxy.
    trust_x_forwarded_for: bool = os.getenv("FMS_TRUST_X_FORWARDED_FOR", "false").strip().lower() in ("1", "true", "yes", "on")

    class Config:
        env_file = ROOT / ".env"
        extra = "ignore"  # tolerate .env keys that don't map to a field (e.g. FMS_AUTH_SECRET)


settings = Settings()

if not settings.auth_secret:
    settings.auth_secret = secrets.token_hex(32)
    try:
        with open(ROOT / ".env", "a", encoding="utf-8") as f:
            f.write(f"\nFMS_AUTH_SECRET={settings.auth_secret}\n")
    except OSError:
        pass  # in-memory secret still works for this process


# Safe default when no config file is present: API-push mode with no bank
# database, so a fresh clone (or CI, or an operator who hasn't written a config
# yet) boots cleanly and can be configured from Administration. bank_config.yaml
# is git-ignored because it holds credentials, so it is absent on fresh checkouts.
_DEFAULT_BANK_CONFIG: dict = {
    "database": {"type": "mysql"},
    "tables": {},
    "monitoring": {"mode": "api", "poll_interval_seconds": 30, "history_days": 90},
}


def load_bank_config() -> dict:
    config_path = ROOT / "bank_config.yaml"
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or dict(_DEFAULT_BANK_CONFIG)
    log.warning(
        "bank_config.yaml not found — starting in API-push mode with no bank database. "
        "Configure ingestion/database under Administration, or copy bank_config.example.yaml."
    )
    return dict(_DEFAULT_BANK_CONFIG)


bank_config: dict = load_bank_config()
