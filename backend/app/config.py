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
    # Signs the Judge Mode visitor cookie. Empty means a random secret per boot, which is fine on
    # one free instance: a restart only makes visitors get a fresh seeded project.
    session_secret: SecretStr = SecretStr("")
    # Display-only sandbox buyer login shown in the banner. Never hardcode or commit a password.
    demo_buyer_email: str = ""
    demo_buyer_password: SecretStr = SecretStr("")
    # A real, already paid sandbox invoice that "Jump to: deposit paid" may adopt after a live GET.
    demo_paid_invoice_id: str = ""
    # Proxy hops that append to X-Forwarded-For. Only the entry they add is trusted.
    trusted_proxy_hops: int = 1

    # Abuse and cost limits (in memory, one instance). They apply in Judge Mode only.
    limit_writes_per_minute_visitor: int = 40
    limit_writes_per_minute_ip: int = 120
    limit_reads_per_minute_ip: int = 600
    limit_llm_per_minute_visitor: int = 6
    limit_llm_per_minute_ip: int = 20
    limit_llm_per_day_visitor: int = 40
    limit_llm_per_day_global: int = 150
    limit_invoices_per_hour_visitor: int = 6
    limit_invoices_per_day_global: int = 60
    limit_projects_per_visitor: int = 5
    reminder_threshold_minutes: int = 60
    # In-process PayPal status polling; 0 turns it off.
    poll_interval_seconds: int = 20

    @property
    def demo_buyer_login(self) -> dict[str, str | None]:
        password = self.demo_buyer_password.get_secret_value()
        return {"email": self.demo_buyer_email or None, "password": password or None}

    @property
    def paypal_base_url(self) -> str:
        return PAYPAL_BASE_URLS[self.paypal_environment]

    @property
    def paypal_configured(self) -> bool:
        return bool(self.paypal_client_id and self.paypal_client_secret.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()
