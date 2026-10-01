# Independent Go backend

This repository owns all StarryNight server code and deployment tools. The
sibling `starrynight` repository owns the clients. The 2026-10-01 migration
preserves the existing chi/Huma + PostgreSQL + Redis + Python architecture;
the uncommitted Gin replacement was discarded at the user's explicit request.

- The user explicitly authorized cutover on 2026-10-01. Production is now
  active at https://39.105.116.74:8443; the old Mac API, AI, PostgreSQL and
  Redis are stopped, and the old AI launchd job is disabled. The user later
  authorized removal of the old Mac runtime and migration snapshots, completed
  on 2026-10-02. See docs/server-cutover-2026-10-01.md.
- Cutover used the existing cloud snapshot (21:51:04 +08:00), with no final
  Mac synchronization or wait for in-flight requests, as explicitly requested.
  The cloud is now authoritative. Do not run standby refresh/activation on
  production or alter its active marker to bypass those scripts' guards.
- Keep this repository independent: no runtime imports, symlinks or implicit
  paths into the client checkout. Authoring uses explicit JSON input/output.
- Commit validated source and documentation to `origin/main` at
  `git@github.com:gukaifeng/starrynight-server.git`; no force pushes or Actions.
- Never commit keys, credentials, voice IDs, conversation snapshots, model
  weights or licensed character binaries. Do not generate new images.

- This directory is a standalone Go module and Docker build context. It must build and test without iOS, Xcode, Unity, licensed characters, or the Python AI worker.
- Public contract: `/v1` HTTP API and generated `api/openapi.json`. Additive fields and namespaced JSON extensions preserve compatibility; incompatible changes require a new API version.
- PostgreSQL is authoritative. Redis holds revocable SCS sessions and distributed rate limits. Never substitute process-local maps or SQLite in integration tests.
- Read the architecture and runbook in `docs/` before changing persistence. Use versioned Goose migrations, explicit ownership predicates, optimistic versions, and cursor pagination. Keep secrets, database files and test captures in ignored `.local/`.
- Guest authentication is opt-in for development/testing and must fail startup in production. No hard-coded privileged/test identity or client-supplied account identity is trusted.
- Use `make test`, `make integration`, and `make build`; document actual measurements rather than claiming an unmeasured concurrency ceiling. Do not invoke paid AI providers in tests.
