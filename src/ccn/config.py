from functools import lru_cache

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CCN_", env_file=".env", extra="ignore")

    github_token: SecretStr | None = Field(default=None, validation_alias="GITHUB_TOKEN")
    seed_repository: str = "NafeesMansoor/CodeCortex"
    max_repositories: int = Field(default=20, ge=1, le=100)
    max_seed_forks: int = Field(default=10, ge=0, le=50)
    max_search_queries: int = Field(default=5, ge=0, le=10)
    max_expansion_seeds: int = Field(default=0, ge=0, le=5)
    max_expansion_queries: int = Field(default=0, ge=0, le=10)
    requests_per_minute: int = Field(default=30, ge=1, le=60)
    request_timeout_seconds: float = Field(default=10, gt=0, le=60)
    github_api_url: str = "https://api.github.com"
    storage_repository: str | None = None
    storage_branch: str = "main"

    @model_validator(mode="after")
    def validate_expansion_limits(self) -> "Settings":
        if bool(self.max_expansion_seeds) != bool(self.max_expansion_queries):
            raise ValueError(
                "max_expansion_seeds and max_expansion_queries must both be zero "
                "or both be positive"
            )
        if self.max_expansion_queries > self.max_search_queries:
            raise ValueError("max_expansion_queries cannot exceed max_search_queries")
        return self

    @field_validator("seed_repository")
    @classmethod
    def validate_seed_repository(cls, value: str) -> str:
        if len(value.split("/")) != 2 or not all(value.split("/")):
            raise ValueError("seed_repository must use owner/name format")
        return value.strip("/")

    @field_validator("storage_repository")
    @classmethod
    def validate_storage_repository(cls, value: str | None) -> str | None:
        if value is not None and (len(value.split("/")) != 2 or not all(value.split("/"))):
            raise ValueError("storage_repository must use owner/name format")
        return value.strip("/") if value else value


@lru_cache
def get_settings() -> Settings:
    return Settings()

