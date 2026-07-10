import os

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://portfolio:portfolio@localhost:5544/portfolio"

    @field_validator("database_url")
    @classmethod
    def _use_psycopg3(cls, v: str) -> str:
        # Providers (Neon, etc.) hand out bare postgresql:// URLs, which SQLAlchemy maps
        # to the psycopg2 driver we don't ship. Force the psycopg (v3) driver.
        for prefix in ("postgresql://", "postgres://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v

    # --- auth / deploy (read from env on Vercel, from .env locally) ---
    google_client_id: str = ""           # OAuth client id == ID-token audience
    session_secret: str = ""             # HS256 signing key for our session cookie
    allowed_emails: str = ""             # comma-separated allowlist
    spending_emails: str = ""            # comma-separated; empty => nobody (fail closed)
    allowed_origins: str = "http://localhost:5173,http://localhost:8000"  # CORS
    cookie_secure: bool = True           # set false for local http dev
    dev_auth_bypass: bool = False        # skip Google auth — LOCAL dev only (see auth_bypass_active)

    @property
    def auth_bypass_active(self) -> bool:
        """Whether the auth gate should be bypassed (treat every request as a dev user).

        Hard guard (SECURITY): the bypass is force-disabled whenever the VERCEL env var is
        present, which every Vercel deployment sets. So DEV_AUTH_BYPASS=true can never unlock
        a deployed environment even if the flag leaks into prod env vars — it is fail-safe by
        construction and only ever active on a local machine."""
        return self.dev_auth_bypass and not os.getenv("VERCEL")

    @property
    def allowed_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.allowed_emails.split(",") if e.strip()}

    @property
    def spending_email_set(self) -> set[str]:
        """Emails allowed to see the Spending feature — a subset of allowed_email_set.

        Empty when SPENDING_EMAILS is unset, which denies everyone (SECURITY-15: fail closed).
        Read fresh on every request, so removing an email revokes access without a redeploy."""
        return {e.strip().lower() for e in self.spending_emails.split(",") if e.strip()}

    @property
    def origin_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


settings = Settings()
