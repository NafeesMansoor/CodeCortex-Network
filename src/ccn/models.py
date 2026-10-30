from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class Repository(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    full_name: str
    html_url: HttpUrl
    description: str | None = None
    language: str | None = None
    topics: list[str] = Field(default_factory=list)
    stargazers_count: int = 0
    forks_count: int = 0
    archived: bool = False
    default_branch: str = "main"
    updated_at: datetime | None = None


class Evidence(BaseModel):
    id: str
    repository_full_name: str
    source_url: HttpUrl
    collected_at: datetime
    source: str
    payload: dict[str, object]


class RelationshipKind(StrEnum):
    SHARED_TOPIC = "shared_topic"
    SEED = "seed"


class Relationship(BaseModel):
    source_repository: str
    target_repository: str
    kind: RelationshipKind
    evidence_ids: list[str] = Field(default_factory=list)
    shared_topics: list[str] = Field(default_factory=list)


class AgentRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class AgentRun(BaseModel):
    id: str
    agent: str = "github_scout"
    status: AgentRunStatus
    started_at: datetime
    finished_at: datetime | None = None
    seed_repository: str
    repositories_seen: int = 0
    evidence_collected: int = 0
    relationships_found: int = 0
    error: str | None = None


class ScoutResult(BaseModel):
    run: AgentRun
    repositories: list[Repository]
    evidence: list[Evidence]
    relationships: list[Relationship]


class RepositoryPage(BaseModel):
    items: list[Repository]
    total: int
    offset: int
    limit: int


class EvidencePage(BaseModel):
    items: list[Evidence]
    total: int
    offset: int
    limit: int


class RelationshipPage(BaseModel):
    items: list[Relationship]
    total: int
    offset: int
    limit: int
