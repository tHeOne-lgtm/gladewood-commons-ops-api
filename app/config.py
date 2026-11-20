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
    # Machine credential for the Command Center sync (Make today, n8n next). Sent as X-Api-Key.
    # Scoped to /api/integrations/* only; it can never reach the staff or admin routes.
    integration_api_key: str = ""
    # Portal v1 (decisions 2026-11-20). Rule 11 router on the Mac mini (n8n) screens every free-text
    # submission before it is stored; unreachable router = hold, log, alert. Files live on the Mac
    # mini (n8n file service) with a Google Drive copy; the API keeps metadata and signs links.
    rule11_router_url: str = ""
    rule11_secret: str = ""
    portal_alert_email: str = ""
    files_service_url: str = ""
    files_service_secret: str = ""
    # Email (Phase 2c, items 9 and 10). Provider "resend" (campaign metrics), "smtp" (Google Workspace,
    # no metrics), or "log" (nothing leaves; rows are still written). Every send carries the postal
    # address and an unsubscribe link, so email_postal_address is required before the first send.
    email_provider: str = "log"
    email_from: str = "Gladewood Commons <hello@gladewoodcommons.com>"
    email_reply_to: str = ""
    email_postal_address: str = ""
    email_unsubscribe_secret: str = ""
    resend_api_key: str = ""
    resend_webhook_secret: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
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
