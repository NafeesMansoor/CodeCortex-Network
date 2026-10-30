from datetime import UTC, datetime

import pytest

from ccn.config import Settings
from ccn.scout import GitHubScout


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
