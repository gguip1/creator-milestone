from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PAYPAL_BASE_URLS = {
    "SANDBOX": "https://api-m.sandbox.paypal.com",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Only SANDBOX is accepted. Live calls are out of scope for this project.
    paypal_environment: Literal["SANDBOX"] = "SANDBOX"
    paypal_client_id: str = ""
    paypal_client_secret: SecretStr = SecretStr("")
    paypal_webhook_id: str = ""
    # Seller (invoicer) and buyer (recipient) sandbox account emails.
    paypal_invoicer_email: str = ""
    paypal_sandbox_buyer_email: str = ""

    llm_provider: str = ""
    llm_model: str = ""
    llm_api_key: SecretStr = SecretStr("")

    database_url: str = "sqlite:///./creatormilestone.db"
    public_base_url: str = "http://localhost:8000"
    judge_mode: bool = False
    recipient_allowlist: list[str] = Field(default_factory=list)
    reminder_threshold_minutes: int = 60
    # In-process PayPal status polling; 0 turns it off.
    poll_interval_seconds: int = 20

    @property
    def paypal_base_url(self) -> str:
        return PAYPAL_BASE_URLS[self.paypal_environment]

    @property
    def paypal_configured(self) -> bool:
        return bool(self.paypal_client_id and self.paypal_client_secret.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()
