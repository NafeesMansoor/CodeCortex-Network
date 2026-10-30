from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx
from fastapi import FastAPI, HTTPException

from ccn.config import get_settings
from ccn.github import GitHubAPIError
from ccn.models import ScoutResult
from ccn.scout import GitHubScout

state: dict[str, object] = {"last_run": None}


@asynccontextmanager
async def lifespan(_: FastAPI):
    scout = GitHubScout(get_settings())
    state["scout"] = scout
    try:
        yield
    finally:
        await scout.close()
        state.pop("scout", None)


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
        "checked_at": datetime.now(UTC).isoformat(),
    }


@app.post("/scout/run", response_model=ScoutResult)
async def scout_run() -> ScoutResult:
    scout = state.get("scout")
    if not isinstance(scout, GitHubScout):
        raise HTTPException(status_code=503, detail="Scout is not initialized")
    try:
        result = await scout.run()
        state["last_run"] = result
        return result
    except (GitHubAPIError, httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/scout/latest", response_model=ScoutResult)
async def scout_latest() -> ScoutResult:
    result = state["last_run"]
    if not isinstance(result, ScoutResult):
        raise HTTPException(status_code=404, detail="No Scout run has completed")
    return result

