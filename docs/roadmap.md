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
- [ ] Add indexed graph queries, incremental record-level updates, historical run browsing, and explicit retention policies.

## Milestone 3 — Broader discovery (planned)

- Add opt-in, bounded discovery strategies beyond seed topics.
- Record discovery paths and support relationship confidence without hiding source evidence.
- Add ranking and filtering with documented signals.

## Milestone 4 — Operability (planned)

- Add background scheduling, run history, structured metrics, and deployment guidance.
- Add service-level access controls and operational hardening.

No deployment or paid resource provisioning is part of the current implementation.
