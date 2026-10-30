from fastapi.testclient import TestClient

from ccn.main import app, state
from ccn.models import (
    Relationship,
    RelationshipKind,
    RunHistoryItem,
    RunHistoryPage,
    ScoutResult,
)
from ccn.storage import GitHubSnapshotStore


def _sample_result() -> ScoutResult:
    return ScoutResult.model_validate(
        {
            "run": {
                "id": "00000000-0000-0000-0000-000000000001",
                "status": "succeeded",
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:01:00Z",
                "seed_repository": "owner/seed",
            },
            "repositories": [
                {
                    "id": 1,
                    "full_name": "owner/seed",
                    "html_url": "https://github.com/owner/seed",
                    "description": "Seed project",
                    "language": "Python",
                    "topics": ["agents", "network"],
                    "stargazers_count": 100,
                },
                {
                    "id": 2,
                    "full_name": "other/agent-kit",
                    "html_url": "https://github.com/other/agent-kit",
                    "description": "Agent helpers",
                    "language": "TypeScript",
                    "topics": ["agents"],
                    "stargazers_count": 10,
                },
            ],
            "evidence": [
                {
                    "id": "ev-1",
                    "repository_full_name": "owner/seed",
                    "source_url": "https://api.github.com/repos/owner/seed",
                    "collected_at": "2026-01-01T00:00:00Z",
                    "source": "repository_metadata",
                    "payload": {"id": 1},
                },
                {
                    "id": "ev-2",
                    "repository_full_name": "other/agent-kit",
                    "source_url": "https://api.github.com/repos/other/agent-kit",
                    "collected_at": "2026-01-01T00:00:00Z",
                    "source": "topic_search",
                    "payload": {"id": 2},
                },
            ],
            "relationships": [
                {
                    "source_repository": "owner/seed",
                    "target_repository": "owner/seed",
                    "kind": "seed",
                    "evidence_ids": ["ev-1"],
                },
                {
                    "source_repository": "owner/seed",
                    "target_repository": "other/agent-kit",
                    "kind": "shared_topic",
                    "evidence_ids": ["ev-2"],
                    "shared_topics": ["agents"],
                },
            ],
        }
    )


def test_health_and_initial_status() -> None:
    state["last_run"] = None
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        status = client.get("/status").json()
        assert status["status"] == "ok"
        assert status["repositories"] == 0


def test_latest_run_not_found_before_scout() -> None:
    state["last_run"] = None
    with TestClient(app) as client:
        assert client.get("/scout/latest").status_code == 404


def test_browse_endpoints_return_typed_paged_snapshot_records() -> None:
    with TestClient(app) as client:
        state["last_run"] = _sample_result()

        repositories = client.get("/repositories", params={"topic": "AGENTS", "limit": 1})
        assert repositories.status_code == 200
        assert repositories.json() == {
            "items": [
                {
                    "id": 1,
                    "full_name": "owner/seed",
                    "html_url": "https://github.com/owner/seed",
                    "description": "Seed project",
                    "language": "Python",
                    "topics": ["agents", "network"],
                    "stargazers_count": 100,
                    "forks_count": 0,
                    "archived": False,
                    "default_branch": "main",
                    "updated_at": None,
                }
            ],
            "total": 2,
            "offset": 0,
            "limit": 1,
        }

        related = client.get("/relationships", params={"repository": "OTHER/AGENT-KIT"})
        assert related.status_code == 200
        assert related.json()["total"] == 1
        assert related.json()["items"][0]["kind"] == "shared_topic"

        evidence = client.get(
            "/evidence", params={"repository": "other/agent-kit", "source": "TOPIC_SEARCH"}
        )
        assert evidence.status_code == 200
        assert evidence.json()["total"] == 1
        assert evidence.json()["items"][0]["id"] == "ev-2"


def test_browse_pagination_filters_and_bounds() -> None:
    with TestClient(app) as client:
        state["last_run"] = _sample_result()

        filtered = client.get("/repositories", params={"q": "agent", "limit": 1})
        assert filtered.status_code == 200
        assert filtered.json()["total"] == 1
        assert filtered.json()["items"][0]["full_name"] == "other/agent-kit"
        page = client.get("/repositories", params={"offset": 1, "limit": 1})
        assert page.status_code == 200
        assert page.json()["total"] == 2
        assert page.json()["items"][0]["full_name"] == "other/agent-kit"
        assert client.get("/evidence", params={"limit": 101}).status_code == 422
        assert client.get("/relationships", params={"offset": -1}).status_code == 422


def test_browse_endpoints_not_found_without_snapshot() -> None:
    state["last_run"] = None
    with TestClient(app) as client:
        for path in ("/repositories", "/relationships", "/evidence"):
            assert client.get(path).status_code == 404


def test_run_history_and_comparison_endpoints(monkeypatch) -> None:
    source = _sample_result()
    source.repositories.append(
        source.repositories[1].model_copy(
            update={"id": 4, "full_name": "other/removed", "stargazers_count": 7}
        )
    )
    source.relationships.append(
        Relationship(
            source_repository="other/removed",
            target_repository="owner/seed",
            kind=RelationshipKind.FORK_OF,
        )
    )
    target = source.model_copy(deep=True)
    target.run = target.run.model_copy(
        update={"id": "00000000-0000-0000-0000-000000000002"}
    )
    target.repositories = [
        source.repositories[0].model_copy(update={"stargazers_count": 105}),
        source.repositories[1].model_copy(update={"stargazers_count": 14}),
        source.repositories[1].model_copy(
            update={"full_name": "other/new-agent", "id": 3, "stargazers_count": 20}
        ),
    ]
    target.relationships = [
        source.relationships[0],
        source.relationships[1].model_copy(update={"shared_topics": ["agents", "tools"]}),
        Relationship(
            source_repository="other/new-agent",
            target_repository="owner/seed",
            kind=RelationshipKind.FORK_OF,
            evidence_ids=["ev-new"],
        ),
    ]
    snapshots = {source.run.id: source, target.run.id: target}
    store = GitHubSnapshotStore(None, "owner/data")  # type: ignore[arg-type]

    async def fake_list_runs(self, offset: int, limit: int) -> RunHistoryPage:
        del self
        all_runs = [source.run, target.run]
        return RunHistoryPage(
            items=[
                RunHistoryItem(run=run, run_file=f"runs/{run.id}.json")
                for run in all_runs[offset : offset + limit]
            ],
            total=len(all_runs),
            offset=offset,
            limit=limit,
        )

    async def fake_load_run(self, run_id: str) -> ScoutResult | None:
        del self
        return snapshots.get(run_id)

    async def fake_load_runs(self, run_ids: list[str]) -> dict[str, ScoutResult]:
        del self
        return {run_id: snapshots[run_id] for run_id in run_ids if run_id in snapshots}

    monkeypatch.setattr(GitHubSnapshotStore, "list_runs", fake_list_runs)
    monkeypatch.setattr(GitHubSnapshotStore, "load_run", fake_load_run)
    monkeypatch.setattr(GitHubSnapshotStore, "load_runs", fake_load_runs)

    with TestClient(app) as client:
        state["store"] = store
        history = client.get("/runs", params={"offset": 1, "limit": 1})
        assert history.status_code == 200
        assert history.json()["total"] == 2
        assert history.json()["items"][0]["run"]["id"] == target.run.id

        detail = client.get(f"/runs/{source.run.id}")
        assert detail.status_code == 200
        assert detail.json()["run"]["id"] == source.run.id

        comparison = client.get(
            f"/runs/{source.run.id}/compare", params={"to_run_id": target.run.id}
        )
        assert comparison.status_code == 200
        body = comparison.json()
        assert body["from_run"]["id"] == source.run.id
        assert body["to_run"]["id"] == target.run.id
        assert [item["full_name"] for item in body["repositories_added"]] == [
            "other/new-agent"
        ]
        assert [item["full_name"] for item in body["repositories_removed"]] == [
            "other/removed"
        ]
        changes = {item["change"]: item for item in body["relationship_changes"]}
        assert set(changes) == {"added", "removed", "updated"}
        assert changes["updated"]["after"]["shared_topics"] == ["agents", "tools"]
        assert body["star_counts"] == {
            "from_seed_repository": "owner/seed",
            "to_seed_repository": "owner/seed",
            "seed_stars": {"from_count": 100, "to_count": 105, "delta": 5},
            "discovered_set_stars": {"from_count": 17, "to_count": 34, "delta": 17},
            "matched_discovered_stars_delta": 4,
            "added_repositories_stars": 20,
            "removed_repositories_stars": 7,
        }


def test_history_requires_github_snapshot_storage() -> None:
    with TestClient(app) as client:
        assert client.get("/runs").status_code == 503
        assert client.get("/runs", params={"limit": 21}).status_code == 422

