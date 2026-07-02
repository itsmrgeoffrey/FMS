import os
import yaml
from pathlib import Path
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

ROOT = Path(__file__).parent.parent


class Settings(BaseSettings):
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    gmail_user: str = os.getenv("GMAIL_USER", "")
    gmail_app_password: str = os.getenv("GMAIL_APP_PASSWORD", "")
    alert_email: str = os.getenv("ALERT_EMAIL", "")
    fms_api_key: str = os.getenv("FMS_API_KEY", "")

    class Config:
        env_file = ROOT / ".env"


settings = Settings()


def load_bank_config() -> dict:
    config_path = ROOT / "bank_config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(
            "bank_config.yaml not found. Copy bank_config.example.yaml and fill it in."
        )
    with open(config_path) as f:
        return yaml.safe_load(f)


bank_config: dict = load_bank_config()
