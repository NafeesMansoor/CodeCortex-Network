# Architecture

## Implemented in the initial milestone

The service is a Python 3.11+ FastAPI application. `ccn.main` exposes health/status routes and runs an on-demand Scout. API responses use Pydantic models defined in `ccn.models`.

`GitHubScout` fetches one configured seed repository, then performs at most `CCN_MAX_SEARCH_QUERIES` searches, one per seed topic. The total unique result set, including the seed, is capped by `CCN_MAX_REPOSITORIES`. Repositories are deduplicated by lowercase `owner/name`. Search results are ranked by stars by GitHub; this is a discovery convenience, not a quality score.

Each seed or discovered repository has an Evidence record with the GitHub source URL, UTC collection timestamp, source type, and original response payload. Relationships currently mean either the seed marker or a shared topic surfaced by a seed-topic search. The evidence IDs are attached to relationships so consumers can trace why a relationship exists.

`GitHubClient` uses only GitHub REST GET requests. It sends the documented API version header, uses optional `GITHUB_TOKEN` authentication, and shares sliding-window limiters across calls handled by one API process. In addition to the configurable overall per-minute cap (maximum 60), conservative guards stay below GitHub's published primary hourly core quota and search quota: 55 core requests per hour and 9 searches per minute without a token, or 4,500 core requests per hour and 30 searches per minute with one. These per-process guards do not account for requests made by other applications using the same IP or token. On a rate-limit response, the client waits according to GitHub's retry/reset headers, or at least one minute for a secondary rate limit, then retries once. Failures are surfaced as an API 502. The API request timeout is configurable.

## Storage and runtime limits

The latest completed result is held in process memory. There is no database, durable evidence archive, run history, background queue, scheduled execution, or cross-worker synchronization. `/status` reports the current process's latest result only. Scout runs are triggered manually through `POST /scout/run`.

## Planned

- Durable repository, evidence, relationship, and run storage with migrations.
- Incremental scans, scheduled runs, and explicit run lifecycle/status tracking for failures.
- Additional discovery sources and relationship types with provenance.
- Authentication, authorization, operational metrics, and deployment configuration.
- Graph query and ranking interfaces.

These are roadmap items, not present capabilities.
