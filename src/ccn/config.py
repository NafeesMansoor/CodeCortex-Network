from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CCN_", env_file=".env", extra="ignore")

    github_token: SecretStr | None = Field(default=None, validation_alias="GITHUB_TOKEN")
    seed_repository: str = "NafeesMansoor/CodeCortex"
    max_repositories: int = Field(default=20, ge=1, le=100)
    max_search_queries: int = Field(default=5, ge=0, le=10)
    requests_per_minute: int = Field(default=30, ge=1, le=60)
    request_timeout_seconds: float = Field(default=10, gt=0, le=60)
    github_api_url: str = "https://api.github.com"

    @field_validator("seed_repository")
    @classmethod
    def validate_seed_repository(cls, value: str) -> str:
        if len(value.split("/")) != 2 or not all(value.split("/")):
            raise ValueError("seed_repository must use owner/name format")
        return value.strip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()

