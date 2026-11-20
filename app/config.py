"""Application settings, read from environment variables or a local .env file."""
from functools import lru_cache

from fastapi import Request
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = "production"
    database_url: str = ""
    cors_origins: str = ""
    supabase_url: str = ""
    supabase_jwt_secret: str = ""
    jwt_audience: str = "authenticated"
    bootstrap_admin_emails: str = ""
    # When true, staff and admin tokens must carry Supabase's `aal` claim at "aal2" (TOTP completed).
    # Turn on only after every staff account has enrolled a factor, or they lock themselves out.
    require_staff_mfa: bool = False
    # Twilio WhatsApp sender (Phase 2a, item 8). Signature validation needs the public URL Twilio calls.
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = ""          # E.164, for example +14155238886
    public_base_url: str = ""               # https://gladewood-commons-ops-api.onrender.com
    twilio_validate_signature: bool = True
    # Public web forms (Phase 2b, item 7). The Netlify outgoing-webhook secret signs form submissions.
    forms_webhook_secret: str = ""
    forms_rate_limit_per_hour: int = 10
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_recycle_seconds: int = 1800

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def bootstrap_admin_set(self) -> set[str]:
        return {e.strip().lower() for e in self.bootstrap_admin_emails.split(",") if e.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()


def settings_dep(request: Request) -> Settings:
    """Settings bound to the running app (lets tests inject their own)."""
    return request.app.state.settings
