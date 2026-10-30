import base64
import json
from typing import Any
from urllib.parse import quote

from ccn.github import GitHubAPIError, GitHubClient
from ccn.models import RunHistoryItem, RunHistoryPage, ScoutResult


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

    async def list_runs(self, offset: int, limit: int) -> RunHistoryPage:
        paths = sorted(await self._run_paths(), reverse=True)
        selected_paths = paths[offset : offset + limit]
        run_ids = [self._run_id_from_path(path) for path in selected_paths]
        results = await self.load_runs(run_ids, paths=selected_paths)
        items = [
            RunHistoryItem(run=results[run_id].run, run_file=path)
            for run_id, path in zip(run_ids, selected_paths, strict=True)
            if run_id in results
        ]
        return RunHistoryPage(items=items, total=len(paths), offset=offset, limit=limit)

    async def load_run(self, run_id: str) -> ScoutResult | None:
        results = await self.load_runs([run_id])
        return results.get(run_id)

    async def load_runs(
        self, run_ids: list[str], paths: list[str] | None = None
    ) -> dict[str, ScoutResult]:
        if paths is None:
            all_paths = await self._run_paths()
            requested = set(run_ids)
            paths = [path for path in all_paths if self._run_id_from_path(path) in requested]
        results: dict[str, ScoutResult] = {}
        for path in paths:
            run_id = self._run_id_from_path(path)
            if run_id not in run_ids:
                continue
            snapshot, _ = await self._read(path)
            if snapshot is not None:
                results[run_id] = ScoutResult.model_validate(snapshot)
        return results

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

    async def _run_paths(self) -> list[str]:
        repository_path = quote(self.repository, safe="/")
        branch = f"heads/{quote(self.branch, safe='')}"
        reference = await self.client.get(f"/repos/{repository_path}/git/ref/{branch}")
        reference_object = reference.get("object") if isinstance(reference, dict) else None
        commit_sha = reference_object.get("sha") if isinstance(reference_object, dict) else None
        if not isinstance(commit_sha, str):
            raise ValueError("GitHub snapshot branch reference is invalid")
        commit = await self.client.get(f"/repos/{repository_path}/git/commits/{commit_sha}")
        commit_tree = commit.get("tree") if isinstance(commit, dict) else None
        tree_sha = commit_tree.get("sha") if isinstance(commit_tree, dict) else None
        if not isinstance(tree_sha, str):
            raise ValueError("GitHub snapshot commit tree is invalid")
        tree = await self.client.get(
            f"/repos/{repository_path}/git/trees/{tree_sha}", {"recursive": "1"}
        )
        if not isinstance(tree, dict):
            raise ValueError("GitHub snapshot repository tree is invalid")
        if tree.get("truncated"):
            raise ValueError("GitHub snapshot repository tree is truncated")
        entries = tree.get("tree")
        if not isinstance(entries, list):
            raise ValueError("GitHub snapshot repository tree is invalid")
        return [
            entry["path"]
            for entry in entries
            if isinstance(entry, dict)
            and entry.get("type") == "blob"
            and isinstance(entry.get("path"), str)
            and entry["path"].startswith("runs/")
            and entry["path"].endswith(".json")
        ]

    @staticmethod
    def _run_id_from_path(path: str) -> str:
        return path.rsplit("/", 1)[-1].removesuffix(".json")

    def _contents_path(self, path: str) -> str:
        encoded_path = quote(path, safe="/")
        repository = quote(self.repository, safe="/")
        return f"/repos/{repository}/contents/{encoded_path}"

    @staticmethod
    def _encode(payload: dict[str, Any]) -> str:
        serialized = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        return base64.b64encode(serialized).decode("ascii")
