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

    # --- spend classification: NL->predicate compile (server-side, once per rule) ---
    anthropic_api_key: str = ""          # server-held; never reaches the browser
    # narrow, closed extraction task — research #4 deliberately picks Haiku over the Opus
    # default; override via env if compound sentences need Sonnet.
    classify_model: str = "claude-haiku-4-5"
    # provider for the NL->predicate compile. "" = auto: Anthropic when a key is set, else the
    # local Ollama server (free + offline). Force with CLASSIFY_PROVIDER=anthropic|ollama|openai.
    # "openai" targets any OpenAI-compatible endpoint (Groq / Gemini / OpenRouter free tiers).
    classify_provider: str = ""
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    # OpenAI-compatible provider (e.g. Groq: base https://api.groq.com/openai/v1)
    openai_base_url: str = ""
    openai_api_key: str = ""
    openai_model: str = ""

    @property
    def classify_provider_active(self) -> str:
        return self.classify_provider or ("anthropic" if self.anthropic_api_key else "ollama")

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
