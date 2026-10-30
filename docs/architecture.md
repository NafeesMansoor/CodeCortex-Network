# Architecture

## Implemented in the initial milestone

The service is a Python 3.11+ FastAPI application. `ccn.main` exposes health/status routes, runs an on-demand Scout, and provides read-only routes for browsing the latest snapshot. API responses use Pydantic models defined in `ccn.models`.

`GitHubScout` fetches one configured seed repository, then at most one first-page request for its direct forks, then performs at most `CCN_MAX_SEARCH_QUERIES` searches, one per seed topic. Fork results are capped by `CCN_MAX_SEED_FORKS` (default 10, maximum 50). The total unique result set, including the seed, is capped by `CCN_MAX_REPOSITORIES`; capacity used by forks reduces the remaining capacity for topic search. Repositories are deduplicated by lowercase `owner/name`. Search results are ranked by stars by GitHub; this is a discovery convenience, not a quality score.

Each seed or discovered repository has an Evidence record with the GitHub source URL, UTC collection timestamp, source type, and original response payload. Relationships include the seed marker, a direct `fork_of` edge from each discovered fork to the seed, or a `shared_topic` edge from the seed to a repository surfaced by a seed-topic search. Fork evidence records the seed's `/forks` endpoint, request parameters, and fork payload under source `seed_forks`; topic discoveries use `topic_search`. Evidence IDs are attached to relationships so consumers can trace why a relationship exists.

`GitHubClient` uses only GitHub REST GET requests. It sends the documented API version header, uses optional `GITHUB_TOKEN` authentication, and shares sliding-window limiters across calls handled by one API process. In addition to the configurable overall per-minute cap (maximum 60), conservative guards stay below GitHub's published primary hourly core quota and search quota: 55 core requests per hour and 9 searches per minute without a token, or 4,500 core requests per hour and 30 searches per minute with one. These per-process guards do not account for requests made by other applications using the same IP or token. On a rate-limit response, the client waits according to GitHub's retry/reset headers, or at least one minute for a secondary rate limit, then retries once. Failures are surfaced as an API 502. The API request timeout is configurable.

## Storage and runtime limits

When `CCN_STORAGE_REPOSITORY` is set, every successful run is written to a unique JSON file under `runs/YYYY/MM/` in that repository. The file contains the typed run result, repositories, source evidence payloads, and relationships. The store then updates `latest.json` with the new run path. Updating this pointer uses the current file SHA and retries conflicts, so concurrent writers don't silently overwrite each other's pointer update. The repository's Git history provides version history and restores.

At startup the API reads `latest.json` and loads the referenced snapshot. A missing pointer means no run has been stored. Storage errors are exposed in `/status`; a run that cannot be persisted returns an error instead of reporting success. The configured GitHub token must have Contents read/write permission on the data repository. Keep that repository private when collected evidence should not be public.

The snapshot store is append-oriented and does not provide indexed graph queries or transactions across the run file and latest pointer. A crash after writing a run file but before updating the pointer can leave an unreferenced snapshot, while the prior latest snapshot remains usable. Without `CCN_STORAGE_REPOSITORY`, the latest result is held in process memory and is lost on restart. There is no background queue, scheduled execution, or cross-worker API cache. Scout runs are triggered manually through `POST /scout/run`.

`GET /repositories`, `GET /relationships`, and `GET /evidence` return paginated records from the latest loaded run only. They accept exact case-insensitive filters for repository language/topic, relationship endpoint/kind, and evidence repository/source; repository search (`q`) matches names and descriptions. The default page size is 50 and the maximum is 100. These routes filter the in-memory snapshot and are not indexed or backed by historical run querying. They return 404 until a latest run is available. `GET /scout/latest` remains the way to retrieve the complete snapshot.

When GitHub snapshot storage is configured, `GET /runs` lists persisted runs in descending snapshot-path order and returns run metadata plus the stored file path. Pages default to 10 runs and are capped at 20; offsets are capped at 10,000. `GET /runs/{run_id}` returns a stored snapshot, and `GET /runs/{run_id}/compare?to_run_id=...` compares two snapshots in that direction. Comparisons report added/removed repositories and added, removed, or semantically updated relationships. Relationship identity is the directed source/target pair plus kind; changes to `shared_topics` are semantic updates, while per-run evidence IDs are deliberately ignored because they naturally differ between scans. Listing a page reads the GitHub repository tree and at most one snapshot per page item; detail and comparison read one or two snapshots. If GitHub reports a truncated tree, the API returns a storage error rather than claim a complete history. These routes require configured GitHub storage, return 503 if it is not configured and 404 for missing run IDs, and do not change stored files.

## Planned

- Indexed graph queries and normalized storage for larger datasets.
- Incremental scans, scheduled runs, and explicit run lifecycle/status tracking for failures.
- Additional discovery sources and relationship types with provenance.
- Additional bounded graph expansion beyond direct seed forks and seed-topic search.
- Authentication, authorization, operational metrics, and deployment configuration.
- Graph query and ranking interfaces.

These are roadmap items, not present capabilities.
