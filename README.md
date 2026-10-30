# CodeCortex Network

CodeCortex Network (CCN) is an early-stage service for discovering repositories related to a seed project and retaining the GitHub evidence behind each relationship.

## First milestone (implemented)

- FastAPI endpoints: `GET /health`, `GET /status`, `POST /scout/run`, and `GET /scout/latest`.
- Typed repository, evidence, relationship, and agent-run models.
- A bounded, read-only GitHub Scout. It fetches the configured seed repository, searches at most the configured number of its topics, deduplicates repositories case-insensitively, and caps the result count.
- Evidence records retain the source URL, collection time, source type, and original GitHub API payload.
- Per-process GitHub request pacing for the core and search quotas, one rate-limit-aware retry, and optional token authentication.
- Pytest suite, Ruff lint configuration, and GitHub Actions CI.

The API currently stores the latest Scout result in process memory. Data is lost when the process restarts, and multiple workers do not share state. Persistent storage, scheduling, richer graph expansion, and production deployment are planned, not implemented.

## Run locally

Python 3.11 or newer is required.

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
uvicorn ccn.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for the API interface. `POST /scout/run` starts a bounded collection. No GitHub token is required, but unauthenticated API access has a lower GitHub rate limit. Set `GITHUB_TOKEN` in the environment or a local, untracked `.env` file to authenticate. Never commit tokens.

Configuration variables are listed in `.env.example`. Repository and query limits are validated and have hard upper bounds. `CCN_REQUESTS_PER_MINUTE` defaults to 30 and cannot exceed 60; additional per-process guards stay below GitHub's published hourly core and per-minute search quotas.

## Verify

```sh
ruff check .
pytest
```

See [docs/architecture.md](docs/architecture.md) and [docs/roadmap.md](docs/roadmap.md) for implemented boundaries and planned work.
