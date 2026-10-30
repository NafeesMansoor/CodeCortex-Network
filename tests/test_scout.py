import base64
import json
from datetime import UTC, datetime

import pytest

from ccn.config import Settings
from ccn.scout import GitHubScout
from ccn.storage import GitHubSnapshotStore


def repo(full_name: str, repo_id: int, topics: list[str]) -> dict:
    return {
        "id": repo_id,
        "full_name": full_name,
        "html_url": f"https://github.com/{full_name}",
        "description": "sample",
        "language": "Python",
        "topics": topics,
        "stargazers_count": 1,
        "forks_count": 0,
        "archived": False,
        "default_branch": "main",
        "updated_at": datetime.now(UTC).isoformat(),
    }


class FakeGitHub:
    def __init__(self, fork_payloads: list[dict] | None = None) -> None:
        self.searches: list[tuple[str, int]] = []
        self.fork_calls: list[tuple[str, int]] = []
        self.fork_payloads = fork_payloads or []

    async def repository(self, _: str) -> dict:
        return repo("owner/seed", 1, ["python", "agents"])

    async def search_repositories(self, query: str, per_page: int) -> list[dict]:
        self.searches.append((query, per_page))
        if query == "topic:python":
            return [repo("owner/seed", 1, ["python"]), repo("other/one", 2, ["python"])]
        return [repo("other/one", 2, ["agents"]), repo("other/two", 3, ["agents"])]

    async def repository_forks(self, full_name: str, per_page: int) -> list[dict]:
        self.fork_calls.append((full_name, per_page))
        return self.fork_payloads


@pytest.mark.asyncio
async def test_scout_deduplicates_retains_evidence_and_obeys_limit() -> None:
    github = FakeGitHub()
    settings = Settings(seed_repository="owner/seed", max_repositories=2, max_search_queries=2)
    result = await GitHubScout(settings, github).run()  # type: ignore[arg-type]

    assert [r.full_name for r in result.repositories] == ["owner/seed", "other/one"]
    assert len(result.evidence) == 2
    assert len(result.relationships) == 2
    assert result.run.repositories_seen == 2
    assert github.searches == [("topic:python", 1)]
    assert github.fork_calls == [("owner/seed", 1)]
    assert result.evidence[0].payload["id"] == 1


@pytest.mark.asyncio
async def test_scout_discovers_bounded_direct_forks_with_provenance() -> None:
    fork = repo("other/fork", 2, ["python"])
    github = FakeGitHub([fork, fork])
    settings = Settings(
        seed_repository="owner/seed",
        max_repositories=3,
        max_seed_forks=2,
        max_search_queries=2,
    )

    result = await GitHubScout(settings, github).run()  # type: ignore[arg-type]

    assert [item.full_name for item in result.repositories] == [
        "owner/seed",
        "other/fork",
        "other/one",
    ]
    assert github.fork_calls == [("owner/seed", 2)]
    fork_relationships = [
        item for item in result.relationships if item.kind.value == "fork_of"
    ]
    assert len(fork_relationships) == 1
    fork_relationship = fork_relationships[0]
    assert fork_relationship.source_repository == "other/fork"
    assert fork_relationship.target_repository == "owner/seed"
    fork_evidence = next(
        item for item in result.evidence if item.id in fork_relationship.evidence_ids
    )
    assert fork_evidence.source == "seed_forks"
    assert fork_evidence.repository_full_name == "other/fork"
    assert str(fork_evidence.source_url).endswith(
        "/repos/owner/seed/forks?per_page=2&sort=newest"
    )
    assert result.run.repositories_seen == len(result.repositories) == 3


@pytest.mark.asyncio
async def test_scout_skips_forks_when_repository_cap_is_reached() -> None:
    github = FakeGitHub([repo("other/fork", 2, ["python"])])
    settings = Settings(
        seed_repository="owner/seed",
        max_repositories=1,
        max_seed_forks=50,
        max_search_queries=0,
    )

    result = await GitHubScout(settings, github).run()  # type: ignore[arg-type]

    assert [item.full_name for item in result.repositories] == ["owner/seed"]
    assert github.fork_calls == []
    assert github.searches == []


@pytest.mark.asyncio
async def test_scout_can_disable_fork_discovery() -> None:
    github = FakeGitHub([repo("other/fork", 2, ["python"])])
    settings = Settings(
        seed_repository="owner/seed",
        max_repositories=5,
        max_seed_forks=0,
        max_search_queries=0,
    )

    result = await GitHubScout(settings, github).run()  # type: ignore[arg-type]

    assert [item.full_name for item in result.repositories] == ["owner/seed"]
    assert github.fork_calls == []


class FakeContentsClient:
    def __init__(self) -> None:
        self.files: dict[str, tuple[str, str]] = {}

    async def request(self, method: str, path: str, params=None, json=None, allow_not_found=False):
        del params
        if method == "GET":
            item = self.files.get(path)
            if item is None and allow_not_found:
                return None
            assert item is not None
            content, sha = item
            return {"content": content, "sha": sha}
        payload = json
        assert payload is not None
        self.files[path] = (payload["content"], f"sha-{len(self.files)}")
        return {}

    async def put(self, path: str, body: dict):
        return await self.request("PUT", path, json=body)

    async def get(self, path: str, params=None):
        del params
        if path.endswith("/git/ref/heads/main"):
            return {"object": {"sha": "commit-sha"}}
        if path.endswith("/git/commits/commit-sha"):
            return {"tree": {"sha": "tree-sha"}}
        if path.endswith("/git/trees/tree-sha"):
            prefix = "/repos/owner/data/contents/"
            return {
                "truncated": False,
                "tree": [
                    {"path": item.removeprefix(prefix), "type": "blob"}
                    for item in self.files
                    if item.startswith(prefix)
                ],
            }
        raise AssertionError(f"Unexpected GitHub API path: {path}")


@pytest.mark.asyncio
async def test_github_snapshot_store_round_trips_versioned_run_and_latest_pointer() -> None:
    github = FakeContentsClient()
    store = GitHubSnapshotStore(github, "owner/data", "main")  # type: ignore[arg-type]
    result = await GitHubScout(Settings(seed_repository="owner/seed"), FakeGitHub()).run()  # type: ignore[arg-type]

    await store.save(result)
    loaded = await store.load_latest()

    assert loaded == result
    assert len(github.files) == 2
    assert any(path.startswith("/repos/owner/data/contents/runs/") for path in github.files)
    pointer_path = "/repos/owner/data/contents/latest.json"
    pointer_raw = base64.b64decode(github.files[pointer_path][0]).decode()
    assert json.loads(pointer_raw)["run_id"] == result.run.id


@pytest.mark.asyncio
async def test_github_snapshot_store_lists_and_loads_a_bounded_history_page() -> None:
    github = FakeContentsClient()
    store = GitHubSnapshotStore(github, "owner/data", "main")  # type: ignore[arg-type]
    scout = GitHubScout(Settings(seed_repository="owner/seed"), FakeGitHub())  # type: ignore[arg-type]
    first = await scout.run()
    second = await scout.run()
    await store.save(first)
    await store.save(second)

    page = await store.list_runs(offset=0, limit=1)
    next_page = await store.list_runs(offset=1, limit=1)

    assert page.total == next_page.total == 2
    assert len(page.items) == len(next_page.items) == 1
    assert {page.items[0].run.id, next_page.items[0].run.id} == {
        first.run.id,
        second.run.id,
    }
    assert (await store.load_run(first.run.id)) == first
