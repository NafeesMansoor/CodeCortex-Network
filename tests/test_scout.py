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
    def __init__(self) -> None:
        self.searches: list[tuple[str, int]] = []

    async def repository(self, _: str) -> dict:
        return repo("owner/seed", 1, ["python", "agents"])

    async def search_repositories(self, query: str, per_page: int) -> list[dict]:
        self.searches.append((query, per_page))
        if query == "topic:python":
            return [repo("owner/seed", 1, ["python"]), repo("other/one", 2, ["python"])]
        return [repo("other/one", 2, ["agents"]), repo("other/two", 3, ["agents"])]


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
    assert result.evidence[0].payload["id"] == 1


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
