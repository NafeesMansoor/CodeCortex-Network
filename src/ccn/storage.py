import base64
import json
from typing import Any
from urllib.parse import quote

from ccn.github import GitHubAPIError, GitHubClient
from ccn.models import ScoutResult


class GitHubSnapshotStore:
    """Versioned JSON snapshots stored as files in a dedicated GitHub repository."""

    def __init__(self, client: GitHubClient, repository: str, branch: str = "main") -> None:
        self.client = client
        self.repository = repository
        self.branch = branch

    async def load_latest(self) -> ScoutResult | None:
        pointer, _ = await self._read("latest.json")
        if pointer is None:
            return None
        run_path = pointer.get("run_file")
        if not isinstance(run_path, str) or not run_path.startswith("runs/"):
            raise ValueError("GitHub snapshot pointer is invalid")
        snapshot, _ = await self._read(run_path)
        if snapshot is None:
            raise ValueError("GitHub snapshot pointer refers to a missing run")
        return ScoutResult.model_validate(snapshot)

    async def save(self, result: ScoutResult) -> None:
        run_path = f"runs/{result.run.started_at:%Y/%m}/{result.run.id}.json"
        snapshot = json.loads(result.model_dump_json())
        await self._write_new(run_path, snapshot, f"Store CCN Scout run {result.run.id}")

        pointer = {"run_file": run_path, "run_id": result.run.id}
        for _ in range(5):
            _, sha = await self._read("latest.json")
            body = {
                "message": f"Update latest CCN Scout run to {result.run.id}",
                "content": self._encode(pointer),
                "branch": self.branch,
            }
            if sha:
                body["sha"] = sha
            try:
                await self.client.put(self._contents_path("latest.json"), body)
                return
            except GitHubAPIError as exc:
                if exc.status_code not in (409, 422):
                    raise
        raise GitHubAPIError("Could not update latest CCN snapshot after concurrent writes", 409)

    async def _write_new(self, path: str, payload: dict[str, Any], message: str) -> None:
        await self.client.put(
            self._contents_path(path),
            {"message": message, "content": self._encode(payload), "branch": self.branch},
        )

    async def _read(self, path: str) -> tuple[dict[str, Any] | None, str | None]:
        response = await self.client.request(
            "GET",
            self._contents_path(path),
            params={"ref": self.branch},
            allow_not_found=True,
        )
        if response is None:
            return None, None
        sha = response.get("sha")
        content = response.get("content")
        if content:
            raw = base64.b64decode(content).decode("utf-8")
            payload = json.loads(raw)
        else:
            payload = await self.client.request(
                "GET",
                self._contents_path(path),
                params={"ref": self.branch},
                allow_not_found=True,
                headers={"Accept": "application/vnd.github.raw+json"},
            )
            if payload is None:
                return None, None
        if not isinstance(payload, dict):
            raise ValueError(f"GitHub snapshot file {path} must contain a JSON object")
        return payload, sha

    def _contents_path(self, path: str) -> str:
        encoded_path = quote(path, safe="/")
        repository = quote(self.repository, safe="/")
        return f"/repos/{repository}/contents/{encoded_path}"

    @staticmethod
    def _encode(payload: dict[str, Any]) -> str:
        serialized = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        return base64.b64encode(serialized).decode("ascii")
