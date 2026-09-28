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

    # audio rooms — unset until a LiveKit Cloud project exists, endpoints 503 until then
    livekit_api_key: str | None = None
    livekit_api_secret: SecretStr | None = None
    livekit_url: str | None = None


settings = Settings()

