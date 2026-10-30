from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID

import httpx
from fastapi import FastAPI, HTTPException, Query

from ccn.config import get_settings
from ccn.github import GitHubAPIError, GitHubClient
from ccn.models import (
    EvidencePage,
    Relationship,
    RelationshipChange,
    RelationshipChangeKind,
    RelationshipKind,
    RelationshipPage,
    RepositoryPage,
    RunComparison,
    RunHistoryPage,
    ScoutResult,
    StarComparisonSummary,
    StarCountChange,
)
from ccn.scout import GitHubScout
from ccn.storage import GitHubSnapshotStore

state: dict[str, object] = {"last_run": None, "store": None, "scout": None}


@asynccontextmanager
async def lifespan(_: FastAPI):
    state["last_run"] = None
    settings = get_settings()
    token = settings.github_token.get_secret_value() if settings.github_token else None
    client = GitHubClient(
        settings.github_api_url,
        token,
        settings.request_timeout_seconds,
        settings.requests_per_minute,
    )
    scout = GitHubScout(settings, client)
    store = (
        GitHubSnapshotStore(client, settings.storage_repository, settings.storage_branch)
        if settings.storage_repository
        else None
    )
    state["scout"] = scout
    state["store"] = store
    state["storage_error"] = None
    if store:
        try:
            state["last_run"] = await store.load_latest()
        except (GitHubAPIError, httpx.HTTPError, ValueError) as exc:
            state["storage_error"] = str(exc)
    try:
        yield
    finally:
        await client.close()
        state.update({"scout": None, "store": None})


app = FastAPI(title="CodeCortex Network API", version="0.1.0", lifespan=lifespan)


def _latest_result() -> ScoutResult:
    result = state["last_run"]
    if not isinstance(result, ScoutResult):
        raise HTTPException(status_code=404, detail="No Scout run has completed")
    return result


def _snapshot_store() -> GitHubSnapshotStore:
    store = state.get("store")
    if not isinstance(store, GitHubSnapshotStore):
        raise HTTPException(status_code=503, detail="GitHub snapshot storage is not configured")
    return store


def _relationship_key(relationship: Relationship) -> tuple[str, str, str]:
    return (
        relationship.source_repository.casefold(),
        relationship.target_repository.casefold(),
        relationship.kind.value,
    )


def _relationship_signature(relationship: Relationship) -> tuple[str, ...]:
    # Evidence IDs change on each run; shared topics define semantic edge changes.
    return tuple(sorted(topic.casefold() for topic in relationship.shared_topics))


def _star_count_change(from_count: int, to_count: int) -> StarCountChange:
    return StarCountChange(from_count=from_count, to_count=to_count, delta=to_count - from_count)


def _compare_runs(source: ScoutResult, target: ScoutResult) -> RunComparison:
    source_repositories = {repo.full_name.casefold(): repo for repo in source.repositories}
    target_repositories = {repo.full_name.casefold(): repo for repo in target.repositories}
    repositories_added = [
        target_repositories[key]
        for key in sorted(target_repositories.keys() - source_repositories.keys())
    ]
    repositories_removed = [
        source_repositories[key]
        for key in sorted(source_repositories.keys() - target_repositories.keys())
    ]

    source_relationships = {
        _relationship_key(item): item for item in source.relationships
    }
    target_relationships = {
        _relationship_key(item): item for item in target.relationships
    }
    changes: list[RelationshipChange] = []
    for key in sorted(source_relationships.keys() | target_relationships.keys()):
        before = source_relationships.get(key)
        after = target_relationships.get(key)
        if before is None:
            changes.append(RelationshipChange(change=RelationshipChangeKind.ADDED, after=after))
        elif after is None:
            changes.append(RelationshipChange(change=RelationshipChangeKind.REMOVED, before=before))
        elif _relationship_signature(before) != _relationship_signature(after):
            changes.append(
                RelationshipChange(
                    change=RelationshipChangeKind.UPDATED, before=before, after=after
                )
            )

    source_seed_key = source.run.seed_repository.casefold()
    target_seed_key = target.run.seed_repository.casefold()
    seed_stars = None
    if source_seed_key == target_seed_key:
        from_seed = source_repositories.get(source_seed_key)
        to_seed = target_repositories.get(target_seed_key)
        if from_seed is not None and to_seed is not None:
            seed_stars = _star_count_change(
                from_seed.stargazers_count, to_seed.stargazers_count
            )

    source_discovered = {
        key: repo for key, repo in source_repositories.items() if key != source_seed_key
    }
    target_discovered = {
        key: repo for key, repo in target_repositories.items() if key != target_seed_key
    }
    common_discovered = source_discovered.keys() & target_discovered.keys()
    star_counts = StarComparisonSummary(
        from_seed_repository=source.run.seed_repository,
        to_seed_repository=target.run.seed_repository,
        seed_stars=seed_stars,
        discovered_set_stars=_star_count_change(
            sum(repo.stargazers_count for repo in source_discovered.values()),
            sum(repo.stargazers_count for repo in target_discovered.values()),
        ),
        matched_discovered_stars_delta=sum(
            target_discovered[key].stargazers_count - source_discovered[key].stargazers_count
            for key in common_discovered
        ),
        added_repositories_stars=sum(
            target_repositories[key].stargazers_count
            for key in target_repositories.keys() - source_repositories.keys()
        ),
        removed_repositories_stars=sum(
            source_repositories[key].stargazers_count
            for key in source_repositories.keys() - target_repositories.keys()
        ),
    )

    return RunComparison(
        from_run=source.run,
        to_run=target.run,
        repositories_added=repositories_added,
        repositories_removed=repositories_removed,
        relationship_changes=changes,
        star_counts=star_counts,
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/status")
async def status() -> dict[str, object]:
    result = state["last_run"]
    return {
        "status": "ok",
        "service": "ccn-api",
        "last_run": result.run.model_dump(mode="json") if isinstance(result, ScoutResult) else None,
        "repositories": len(result.repositories) if isinstance(result, ScoutResult) else 0,
        "evidence": len(result.evidence) if isinstance(result, ScoutResult) else 0,
        "relationships": len(result.relationships) if isinstance(result, ScoutResult) else 0,
        "storage": "github" if isinstance(state.get("store"), GitHubSnapshotStore) else "memory",
        "storage_error": state.get("storage_error"),
        "checked_at": datetime.now(UTC).isoformat(),
    }


@app.post("/scout/run", response_model=ScoutResult)
async def scout_run() -> ScoutResult:
    scout = state.get("scout")
    if not isinstance(scout, GitHubScout):
        raise HTTPException(status_code=503, detail="Scout is not initialized")
    try:
        result = await scout.run()
        store = state.get("store")
        if isinstance(store, GitHubSnapshotStore):
            await store.save(result)
        state["last_run"] = result
        state["storage_error"] = None
        return result
    except (GitHubAPIError, httpx.HTTPError, ValueError) as exc:
        state["storage_error"] = str(exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/scout/latest", response_model=ScoutResult)
async def scout_latest() -> ScoutResult:
    return _latest_result()


@app.get("/repositories", response_model=RepositoryPage)
async def repositories(
    q: str | None = Query(default=None, min_length=1, max_length=200),
    language: str | None = Query(default=None, min_length=1, max_length=100),
    topic: str | None = Query(default=None, min_length=1, max_length=100),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> RepositoryPage:
    result = _latest_result()
    records = result.repositories
    if q:
        needle = q.casefold()
        records = [
            record
            for record in records
            if needle in record.full_name.casefold()
            or needle in (record.description or "").casefold()
        ]
    if language:
        records = [
            record
            for record in records
            if (record.language or "").casefold() == language.casefold()
        ]
    if topic:
        records = [
            record
            for record in records
            if any(item.casefold() == topic.casefold() for item in record.topics)
        ]
    return RepositoryPage(
        items=records[offset : offset + limit], total=len(records), offset=offset, limit=limit
    )


@app.get("/relationships", response_model=RelationshipPage)
async def relationships(
    repository: str | None = Query(default=None, min_length=1, max_length=200),
    kind: RelationshipKind | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> RelationshipPage:
    result = _latest_result()
    records = result.relationships
    if repository:
        name = repository.casefold()
        records = [
            record
            for record in records
            if record.source_repository.casefold() == name
            or record.target_repository.casefold() == name
        ]
    if kind:
        records = [record for record in records if record.kind == kind]
    return RelationshipPage(
        items=records[offset : offset + limit], total=len(records), offset=offset, limit=limit
    )


@app.get("/evidence", response_model=EvidencePage)
async def evidence(
    repository: str | None = Query(default=None, min_length=1, max_length=200),
    source: str | None = Query(default=None, min_length=1, max_length=100),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> EvidencePage:
    result = _latest_result()
    records = result.evidence
    if repository:
        name = repository.casefold()
        records = [record for record in records if record.repository_full_name.casefold() == name]
    if source:
        source_name = source.casefold()
        records = [record for record in records if record.source.casefold() == source_name]
    return EvidencePage(
        items=records[offset : offset + limit], total=len(records), offset=offset, limit=limit
    )


@app.get("/runs", response_model=RunHistoryPage)
async def runs(
    offset: int = Query(default=0, ge=0, le=10000),
    limit: int = Query(default=10, ge=1, le=20),
) -> RunHistoryPage:
    store = _snapshot_store()
    try:
        return await store.list_runs(offset, limit)
    except (GitHubAPIError, httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/runs/{run_id}", response_model=ScoutResult)
async def run_detail(run_id: UUID) -> ScoutResult:
    store = _snapshot_store()
    try:
        result = await store.load_run(str(run_id))
    except (GitHubAPIError, httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Scout run not found")
    return result


@app.get("/runs/{from_run_id}/compare", response_model=RunComparison)
async def compare_runs(from_run_id: UUID, to_run_id: UUID) -> RunComparison:
    store = _snapshot_store()
    source_id = str(from_run_id)
    target_id = str(to_run_id)
    try:
        results = await store.load_runs([source_id, target_id])
    except (GitHubAPIError, httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    source = results.get(source_id)
    target = results.get(target_id)
    if source is None or target is None:
        raise HTTPException(status_code=404, detail="One or both Scout runs were not found")
    return _compare_runs(source, target)

