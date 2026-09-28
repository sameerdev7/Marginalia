from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    secret_key: SecretStr
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # sqlite locally by default; set DATABASE_URL in production to a
    # postgresql+asyncpg:// URL (e.g. Neon) — same code path either way,
    # SQLAlchemy picks the driver from the URL's scheme.
    database_url: str = "sqlite+aiosqlite:///./athenaeum.db"

    # frontend origin(s) allowed to call this API, comma-separated. The
    # local Vite dev server by default; set to the deployed frontend's real
    # origin in production, never "*" once cookies/auth headers are in play.
    cors_origins: str = "http://localhost:5173"

    # audio rooms — unset until a LiveKit Cloud project exists, endpoints 503 until then
    livekit_api_key: str | None = None
    livekit_api_secret: SecretStr | None = None
    livekit_url: str | None = None


settings = Settings()

