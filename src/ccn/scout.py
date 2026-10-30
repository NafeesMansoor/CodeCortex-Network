from datetime import UTC, datetime
from uuid import uuid4

from ccn.config import Settings
from ccn.github import GitHubClient
from ccn.models import (
    AgentRun,
    AgentRunStatus,
    Evidence,
    EvidenceSource,
    Relationship,
    RelationshipKind,
    Repository,
    ScoutResult,
)


class GitHubScout:
    def __init__(self, settings: Settings, client: GitHubClient | None = None) -> None:
        self.settings = settings
        token = settings.github_token.get_secret_value() if settings.github_token else None
        self.client = client or GitHubClient(
            settings.github_api_url,
            token,
            settings.request_timeout_seconds,
            settings.requests_per_minute,
        )
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self.client.close()

    async def run(self) -> ScoutResult:
        started = datetime.now(UTC)
        run_id = str(uuid4())
        repositories: dict[str, Repository] = {}
        evidence: list[Evidence] = []
        relationships: list[Relationship] = []

        seed_payload = await self.client.repository(self.settings.seed_repository)
        seed = Repository.model_validate(seed_payload)
        repositories[seed.full_name.lower()] = seed
        seed_evidence = self._evidence(
            seed, seed_payload, "/repos/" + seed.full_name, EvidenceSource.REPOSITORY_METADATA
        )
        evidence.append(seed_evidence)
        relationships.append(Relationship(
            source_repository=seed.full_name,
            target_repository=seed.full_name,
            kind=RelationshipKind.SEED,
            evidence_ids=[seed_evidence.id],
        ))

        # The forks endpoint makes one bounded core request and provides direct provenance.
        fork_limit = min(
            self.settings.max_seed_forks, self.settings.max_repositories - len(repositories)
        )
        if fork_limit > 0:
            fork_payloads = await self.client.repository_forks(seed.full_name, fork_limit)
            for payload in fork_payloads[:fork_limit]:
                repository = Repository.model_validate(payload)
                key = repository.full_name.casefold()
                if key in repositories or len(repositories) >= self.settings.max_repositories:
                    continue
                repositories[key] = repository
                fork_evidence = self._evidence(
                    repository,
                    payload,
                    f"/repos/{seed.full_name}/forks?per_page={fork_limit}&sort=newest",
                    EvidenceSource.SEED_FORKS,
                )
                evidence.append(fork_evidence)
                relationships.append(Relationship(
                    source_repository=repository.full_name,
                    target_repository=seed.full_name,
                    kind=RelationshipKind.FORK_OF,
                    evidence_ids=[fork_evidence.id],
                ))

        queries = [f"topic:{topic}" for topic in seed.topics[: self.settings.max_search_queries]]
        for query in queries:
            remaining = self.settings.max_repositories - len(repositories)
            if remaining <= 0:
                break
            items = await self.client.search_repositories(query, remaining)
            for payload in items:
                repository = Repository.model_validate(payload)
                key = repository.full_name.lower()
                if key in repositories or len(repositories) >= self.settings.max_repositories:
                    continue
                repositories[key] = repository
                source_url = f"/search/repositories?q={query}"
                item_evidence = self._evidence(
                    repository, payload, source_url, EvidenceSource.TOPIC_SEARCH
                )
                evidence.append(item_evidence)
                shared = sorted(set(seed.topics).intersection(repository.topics))
                relationships.append(Relationship(
                    source_repository=seed.full_name,
                    target_repository=repository.full_name,
                    kind=RelationshipKind.SHARED_TOPIC,
                    evidence_ids=[seed_evidence.id, item_evidence.id],
                    shared_topics=shared,
                ))

        finished = datetime.now(UTC)
        run = AgentRun(
            id=run_id,
            status=AgentRunStatus.SUCCEEDED,
            started_at=started,
            finished_at=finished,
            seed_repository=seed.full_name,
            repositories_seen=len(repositories),
            evidence_collected=len(evidence),
            relationships_found=len(relationships),
        )
        return ScoutResult(
            run=run,
            repositories=list(repositories.values()),
            evidence=evidence,
            relationships=relationships,
        )

    def _evidence(
        self, repository: Repository, payload: dict, path: str, source: EvidenceSource
    ) -> Evidence:
        return Evidence(
            id=str(uuid4()),
            repository_full_name=repository.full_name,
            source_url=f"{self.settings.github_api_url.rstrip('/')}{path}",
            collected_at=datetime.now(UTC),
            source=source,
            payload=payload,
        )
