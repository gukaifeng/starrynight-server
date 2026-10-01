# Independent Go backend

This repository owns all StarryNight server code and deployment tools. The
sibling `starrynight` repository owns the clients. The 2026-10-01 migration
preserves the existing chi/Huma + PostgreSQL + Redis + Python architecture;
the uncommitted Gin replacement was discarded at the user's explicit request.

- Never stop/restart the existing Mac deployment or switch clients until the
  user explicitly authorizes cutover. Preparation only operates on the cloud
  standby and this repository's separately named development instances.
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
