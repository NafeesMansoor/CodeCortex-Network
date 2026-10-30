# Roadmap

## Milestone 1 — API and bounded GitHub Scout (implemented)

- FastAPI health, status, run, and latest-result endpoints.
- Typed repository, evidence, relationship, and agent-run models.
- Read-only, topic-based Scout seeded from `NafeesMansoor/CodeCortex` by default.
- Configurable hard-bounded repository/query counts, request pacing, timeout, and optional token.
- Case-insensitive deduplication and retained GitHub response evidence.
- Pytest, Ruff, and GitHub Actions CI.

## Milestone 2 — GitHub snapshot persistence (partially implemented)

- [x] Persist each Scout run, repository, evidence payload, and relationship as a versioned JSON snapshot in a configurable GitHub repository.
- [x] Restore the latest completed run at API startup and update the latest pointer with optimistic concurrency.
- [x] Add read-only paginated browse endpoints for repositories, relationships, and evidence in the latest snapshot.
- [x] Add bounded paginated persisted run history, run detail, and directional run-to-run comparisons.
- [x] Include seed and discovered-set star count changes in comparisons as observational measurements.
- [ ] Add indexed graph queries, incremental record-level updates, and explicit retention policies.

## Milestone 3 — Broader discovery (partially implemented)

- [x] Add bounded first-page discovery of direct seed forks, with configurable limits and typed `fork_of` relationships linked to source evidence.
- [x] Add opt-in one-hop topic expansion from a capped set of first-hop repositories, under a global search-query budget and total repository cap.
- [x] Record directed `discovered_via` relationships with source and target evidence; skip already-seen targets to prevent cycles.
- [ ] Add deeper discovery paths and support relationship confidence without hiding source evidence.
- [ ] Add ranking and filtering with documented signals.

## Milestone 4 — Operability (planned)

- Add background scheduling, structured metrics, and deployment guidance.
- Add service-level access controls and operational hardening.

No deployment or paid resource provisioning is part of the current implementation.
