from fastapi.testclient import TestClient

from ccn.main import app, state
from ccn.models import ScoutResult


def _sample_result() -> ScoutResult:
    return ScoutResult.model_validate(
        {
            "run": {
                "id": "run-1",
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
                },
                {
                    "id": 2,
                    "full_name": "other/agent-kit",
                    "html_url": "https://github.com/other/agent-kit",
                    "description": "Agent helpers",
                    "language": "TypeScript",
                    "topics": ["agents"],
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
                    "stargazers_count": 0,
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

