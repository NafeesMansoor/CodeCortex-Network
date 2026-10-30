import asyncio
import time
from collections import deque
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx


class GitHubAPIError(RuntimeError):
    """GitHub rejected or could not fulfill a request."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class RequestLimiter:
    """A sliding-window limiter shared by a running API process."""

    def __init__(self, limit: int, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.calls: deque[float] = deque()

    async def wait(self) -> None:
        while True:
            now = time.monotonic()
            while self.calls and now - self.calls[0] >= self.window_seconds:
                self.calls.popleft()
            if len(self.calls) < self.limit:
                break
            await asyncio.sleep(max(0.0, self.window_seconds - (now - self.calls[0])))
        self.calls.append(time.monotonic())


class GitHubClient:
    def __init__(self, api_url: str, token: str | None, timeout: float, rpm: int) -> None:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.client = httpx.AsyncClient(
            base_url=api_url.rstrip("/"), headers=headers, timeout=timeout
        )
        self.limiter = RequestLimiter(rpm)
        self.search_limiter = RequestLimiter(30 if token else 9)
        self.hourly_limiter = RequestLimiter(4500 if token else 55, 3600)

    async def close(self) -> None:
        await self.client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        allow_not_found: bool = False,
        headers: dict[str, str] | None = None,
    ) -> Any:
        async def request() -> httpx.Response:
            await self.hourly_limiter.wait()
            await self.limiter.wait()
            if path.startswith("/search/"):
                await self.search_limiter.wait()
            return await self.client.request(
                method, path, params=params, json=json, headers=headers
            )

        response = await request()
        if response.status_code in (403, 429):
            remaining = response.headers.get("X-RateLimit-Remaining")
            reset = response.headers.get("X-RateLimit-Reset")
            retry_after = response.headers.get("Retry-After")
            message = response.text.lower()
            is_rate_limited = (
                response.status_code == 429
                or remaining == "0"
                or retry_after is not None
                or "rate limit" in message
            )
            if not is_rate_limited:
                raise GitHubAPIError(
                    f"GitHub API returned {response.status_code} for {path}", response.status_code
                )
            if retry_after:
                delay = max(0.0, float(retry_after))
            elif remaining == "0" and reset:
                delay = max(0.0, float(reset) - time.time())
            else:
                delay = 60.0
            await asyncio.sleep(delay)
            response = await request()
        if response.status_code >= 400:
            if allow_not_found and response.status_code == 404:
                return None
            raise GitHubAPIError(
                f"GitHub API returned {response.status_code} for {path}", response.status_code
            )
        return response.json()

    async def get(self, path: str, params: dict[str, str] | None = None) -> Any:
        return await self.request("GET", path, params=params)

    async def put(self, path: str, body: dict[str, Any]) -> Any:
        return await self.request("PUT", path, json=body)

    async def repository(self, full_name: str) -> dict[str, Any]:
        return await self.get(f"/repos/{quote(full_name, safe='/')}")

    async def repository_forks(self, full_name: str, per_page: int) -> list[dict[str, Any]]:
        data = await self.get(
            f"/repos/{quote(full_name, safe='/')}/forks",
            {"per_page": str(per_page), "sort": "newest"},
        )
        return data

    async def search_repositories(self, query: str, per_page: int) -> list[dict[str, Any]]:
        data = await self.get(
            "/search/repositories",
            {"q": query, "per_page": str(per_page), "sort": "stars"},
        )
        return data.get("items", [])

    @staticmethod
    def timestamp() -> datetime:
        return datetime.now(UTC)

