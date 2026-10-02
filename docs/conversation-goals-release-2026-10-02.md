# Conversation goals release — 2026-10-02

The first goal implementation and its client are complete. Architecture and
ownership are defined in `design/conversation-goals-2026-10-02.md`.
The active cloud release is `20261002T033724Z-98e401ee29c8`, code commit
`98e401ee29c876705d19398dd685a0301ccf0842`.

## Validation and the provider issue

- AI pipeline: 231 passed, 4 existing conditional skips. No paid provider calls
  in this test suite.
- Real PostgreSQL/Redis API integration, Go race checks, vet, build and OpenAPI
  generation passed. The local two-replica sample is a functional workload,
  not a claim about production capacity.
- Cloud public checks: 25 passed, including revocable authentication, ownership,
  configuration CAS, reset, and blocked private feedback routes.
- Initial two text-only provider calls correctly followed relationship and
  English-task modes, but omitted optional `goal_feedback`. Tests had checked
  the protocol adapter, not real provider completeness. Progress stayed zero.
- Real user/story turns now use required grounded feedback wire schemas, with
  quoted user evidence and all four dimensions. Other trigger and legacy schemas
  stay compatible. Feedback remains part of the normal planning call.
- Final two text-only calls verified relationship and English-task replies,
  progress versions 1 then 2, shared bond persistence, no Chinese in the English
  reply, pause/reset and config retention. Disposable accounts were deleted.
  Results are local `.local/logs/goal-cloud-final-check.json`.
- Four text-only test turns in total were used for this release investigation.
  No test image or voice generation was requested. The final two request timings
  are not phone speech latency or rendering measurements.

## Deployment

The installer verified all immutable release files, took an online SQLite backup
and PostgreSQL dump, ran additive migration 9, switched the active release and
restarted API/AI with readiness checks. Private feedback is limited to the
loopback gateway and its separate service credential; Caddy blocks `/internal/*`.

Latest pre-upgrade backup:
`/home/starrynight/app/backups/before-api-20261002T033724Z-98e401ee29c8`.
Previous release and backups were retained. No Mac business services were restored.

Client 0.87.0 (117) passed three native UI checks, signed Release compilation and
iPhone installation. Remote launch was blocked by the locked phone, so actual
phone interaction and sustained conversation quality were not asserted.

## Practical limits

The worker journal and PG feedback are separate transactions. Request UUID
deduplication and configuration checks are implemented; atomic cross-database
delivery is not. A PG outbox/journal consolidation remains a future improvement.
Milestones require evidence but model feedback still needs behavioural review.
Coupling is explicitly user-confirmed; no score grants consent or ends the story.
Reviewed adult romance defaults currently cover Mafuyu and Ichigo, while other
roles retain their authored age/language boundaries and non-romantic directions.
