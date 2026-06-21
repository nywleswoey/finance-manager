from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://portfolio:portfolio@localhost:5544/portfolio"

    # --- auth / deploy (read from env on Vercel, from .env locally) ---
    google_client_id: str = ""           # OAuth client id == ID-token audience
    session_secret: str = ""             # HS256 signing key for our session cookie
    allowed_emails: str = ""             # comma-separated allowlist
    allowed_origins: str = "http://localhost:5173,http://localhost:8000"  # CORS
    cookie_secure: bool = True           # set false for local http dev

    @property
    def allowed_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.allowed_emails.split(",") if e.strip()}

    @property
    def origin_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


settings = Settings()
