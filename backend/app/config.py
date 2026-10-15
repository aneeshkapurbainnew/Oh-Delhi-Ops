from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://ohd:ohd@localhost:5432/ohd"
    # Signs session cookies. Generate with: python -c "import secrets; print(secrets.token_urlsafe(48))"
    app_secret: str = "change-me-in-production"
    session_hours: int = 72
    cookie_secure: bool = True  # set false only for local http development
    upload_dir: str = "./uploads"
    # bill photos: "local" (server disk) or "supabase" (private Supabase Storage bucket, accessed only
    # by the backend, so browsers never contact supabase.co)
    storage_backend: str = "local"
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    storage_bucket: str = "bills"
    auth_disabled: bool = False  # tests / local experiments only
    cors_origins: str = "http://localhost:5173"
    default_outlet_id: int = 1

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
