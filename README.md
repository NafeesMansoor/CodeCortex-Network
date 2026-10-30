# CodeCortex Network

CodeCortex Network (CCN) is an early-stage service for discovering repositories related to a seed project and retaining the GitHub evidence behind each relationship.

## First milestone (implemented)

- FastAPI endpoints: `GET /health`, `GET /status`, `POST /scout/run`, `GET /scout/latest`, paginated browse routes for `/repositories`, `/relationships`, and `/evidence`, plus persisted history at `GET /runs`, `GET /runs/{run_id}`, and directional comparisons at `GET /runs/{run_id}/compare?to_run_id=...`.
- Typed repository, evidence, relationship, and agent-run models.
- A bounded, read-only GitHub Scout. It fetches the configured seed repository, optionally collects a bounded page of direct forks, then searches seed topics. Optional one-hop expansion can search topics from a capped set of first-hop discoveries. Repositories are deduplicated case-insensitively and the total result count stays within its configured cap.
- Evidence records retain the source URL, collection time, source type, and original GitHub API payload.
- Run comparisons summarize observed seed and discovered-repository star counts, including changes among matched repositories and totals for additions/removals. These are snapshot measurements; they do not show that CCN caused stars to increase. CCN does not promote repositories or perform engagement actions.
- Per-process GitHub request pacing for the core and search quotas, one rate-limit-aware retry, and optional token authentication.
- Optional durable storage as versioned JSON run files in a dedicated GitHub repository, with `latest.json` updated using optimistic concurrency.
- Pytest suite, Ruff lint configuration, and GitHub Actions CI.

When `CCN_STORAGE_REPOSITORY` is unset, the API keeps the latest result in process memory; it is lost on restart and is not shared across workers. For durable storage, configure a dedicated private GitHub repository and give `GITHUB_TOKEN` Contents read/write access to it. Each completed run is saved as a versioned JSON file, and a small pointer identifies the latest run. Latest-snapshot browse routes filter in-memory data; persisted history routes read from the GitHub repository. These are bounded file-based queries, not indexed graph queries. Scheduling, richer graph expansion, and production deployment are planned.

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

Configuration variables are listed in `.env.example`. Repository and query limits are validated and have hard upper bounds. `CCN_MAX_SEED_FORKS` defaults to 10 and is capped at 50; set it to 0 to disable fork discovery. `CCN_MAX_SEARCH_QUERIES` is the total search-query budget for one run. Expansion is off by default; set both `CCN_MAX_EXPANSION_SEEDS` (up to 5 first-hop repositories) and `CCN_MAX_EXPANSION_QUERIES` (up to 10 queries, reserved from the total query budget) above zero to enable it. For example, total 8 queries with 2 expansion queries leaves up to 6 for seed topics and reserves up to 2 for expansion. `CCN_REQUESTS_PER_MINUTE` defaults to 30 and cannot exceed 60; additional per-process guards stay below GitHub's published hourly core and per-minute search quotas. Set `CCN_STORAGE_REPOSITORY=owner/private-repo` and `CCN_STORAGE_BRANCH=main` to enable durable storage. No repo is created automatically.

## Verify

```sh
ruff check .
pytest
```

See [docs/architecture.md](docs/architecture.md) and [docs/roadmap.md](docs/roadmap.md) for implemented boundaries and planned work.
