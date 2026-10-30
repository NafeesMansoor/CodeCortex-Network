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
        repository_evidence: dict[str, Evidence] = {}
        evidence: list[Evidence] = []
        relationships: list[Relationship] = []
        first_hop_repositories: list[Repository] = []

        seed_payload = await self.client.repository(self.settings.seed_repository)
        seed = Repository.model_validate(seed_payload)
        seed_key = seed.full_name.casefold()
        repositories[seed_key] = seed
        seed_evidence = self._evidence(
            seed, seed_payload, "/repos/" + seed.full_name, EvidenceSource.REPOSITORY_METADATA
        )
        evidence.append(seed_evidence)
        repository_evidence[seed_key] = seed_evidence
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
                first_hop_repositories.append(repository)
                fork_evidence = self._evidence(
                    repository,
                    payload,
                    f"/repos/{seed.full_name}/forks?per_page={fork_limit}&sort=newest",
                    EvidenceSource.SEED_FORKS,
                )
                evidence.append(fork_evidence)
                repository_evidence[key] = fork_evidence
                relationships.append(Relationship(
                    source_repository=repository.full_name,
                    target_repository=seed.full_name,
                    kind=RelationshipKind.FORK_OF,
                    evidence_ids=[fork_evidence.id],
                ))

        expansion_enabled = self.settings.max_expansion_seeds > 0
        expansion_reserve = (
            self.settings.max_expansion_queries
            if expansion_enabled
            else 0
        )
        seed_query_budget = self.settings.max_search_queries - expansion_reserve
        seed_topics: list[str] = []
        seen_topics: set[str] = set()
        for topic in seed.topics:
            topic_key = topic.casefold()
            if topic_key not in seen_topics:
                seen_topics.add(topic_key)
                seed_topics.append(topic)
        seed_queries_used = 0
        searched_topics: set[str] = set()
        for topic in seed_topics[:seed_query_budget]:
            remaining = self.settings.max_repositories - len(repositories)
            if remaining <= 0:
                break
            query = f"topic:{topic}"
            items = await self.client.search_repositories(query, remaining)
            seed_queries_used += 1
            searched_topics.add(topic.casefold())
            for payload in items:
                repository = Repository.model_validate(payload)
                key = repository.full_name.casefold()
                if key in repositories or len(repositories) >= self.settings.max_repositories:
                    continue
                repositories[key] = repository
                first_hop_repositories.append(repository)
                source_url = f"/search/repositories?q={query}"
                item_evidence = self._evidence(
                    repository, payload, source_url, EvidenceSource.TOPIC_SEARCH
                )
                evidence.append(item_evidence)
                repository_evidence[key] = item_evidence
                shared = sorted(set(seed.topics).intersection(repository.topics))
                relationships.append(Relationship(
                    source_repository=seed.full_name,
                    target_repository=repository.full_name,
                    kind=RelationshipKind.SHARED_TOPIC,
                    evidence_ids=[seed_evidence.id, item_evidence.id],
                    shared_topics=shared,
                ))

        expansion_queries_used = 0
        expansion_query_budget = min(
            self.settings.max_expansion_queries,
            self.settings.max_search_queries - seed_queries_used,
        )
        expansion_seeds = first_hop_repositories[: self.settings.max_expansion_seeds]
        for expansion_seed in expansion_seeds:
            if expansion_queries_used >= expansion_query_budget:
                break
            remaining = self.settings.max_repositories - len(repositories)
            if remaining <= 0:
                break
            topic = next(
                (item for item in expansion_seed.topics if item.casefold() not in searched_topics),
                None,
            )
            if topic is None:
                continue
            query = f"topic:{topic}"
            source_key = expansion_seed.full_name.casefold()
            source_evidence = repository_evidence.get(source_key)
            if source_evidence is None:
                continue
            items = await self.client.search_repositories(query, remaining)
            expansion_queries_used += 1
            searched_topics.add(topic.casefold())
            for payload in items:
                repository = Repository.model_validate(payload)
                key = repository.full_name.casefold()
                # Already-seen names include the seed and expansion source; skipping them
                # prevents case-only duplicates, self-links, and cycles back into the graph.
                if key in repositories or len(repositories) >= self.settings.max_repositories:
                    continue
                repositories[key] = repository
                item_evidence = self._evidence(
                    repository,
                    payload,
                    f"/search/repositories?q={query}",
                    EvidenceSource.EXPANSION_TOPIC_SEARCH,
                )
                evidence.append(item_evidence)
                repository_evidence[key] = item_evidence
                shared = sorted(
                    set(expansion_seed.topics).intersection(repository.topics), key=str.casefold
                )
                relationships.append(Relationship(
                    source_repository=expansion_seed.full_name,
                    target_repository=repository.full_name,
                    kind=RelationshipKind.DISCOVERED_VIA,
                    evidence_ids=[source_evidence.id, item_evidence.id],
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
