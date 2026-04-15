from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    api_key: SecretStr
    database_url: str
    rabbit_url: str
    outbox_poll_interval_s: float = 0.5
    outbox_batch_size: int = 100
    retry_delays_s: tuple[int, int] = (5, 15)
    gateway_success_rate: float = 0.95
    consumer_prefetch_count: int = 1
    webhook_timeout_s: float = 5.0

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
