from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx
from fastapi import FastAPI, HTTPException

from ccn.config import get_settings
from ccn.github import GitHubAPIError, GitHubClient
from ccn.models import ScoutResult
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
    result = state["last_run"]
    if not isinstance(result, ScoutResult):
        raise HTTPException(status_code=404, detail="No Scout run has completed")
    return result

