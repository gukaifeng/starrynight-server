# Goal-driven conversations v1

StarryNight now separates user-owned direction from AI-proposed progress. Goals
are not a replacement for a persona or chat history. The same goal context is
supplied to ordinary replies, greetings, idle speech, gesture reactions,
suggestions, speculative answer branches and parallel performance selection.

## Product contract

Three modes share an account/character-scoped state:

| Mode | Primary direction | Secondary direction |
|---|---|---|
| relationship | A believable relationship; eligible adult romance prioritised | Interesting everyday conversation |
| task | Studying, English practice, listening or planning | Warm in-character companionship |
| sandbox | Understanding, interest and persona consistency | No required ending |

The user chooses initial relation, long-term direction, a free-form short-term
wish and whether progress is paused. Initial relations: strangers, pursuit,
flirting, lovers, friends, mentor, rivals and childhood. Romance requires an
explicitly authored adult persona that permits it. The current reviewed allowlist
is Mafuyu (26) and Ichigo (24). Lime and Nozomi default to English practice.
Other personas share the three modes with non-romantic relationship branches;
unknown ages or a childlike persona are not silently rewritten as adults.

The model receives relationship/task priorities of 0.85/0.15 or 0.2/0.8 as
prompt guidance, not calibrated probabilities or a deterministic outcome rule.
Sandbox directions are understanding, interest and persona consistency. Existing
authored character boundaries and English-only personas remain stronger than a
requested mode. Short-term text is user intent, never privileged instructions.

Romance does not end the experience: pursuit, mutual interest, confirmed couple
and everyday couple life remain open-ended. The user can confirm an existing
relationship or select an initial lovers setup. No score threshold confirms a
relationship. Refusal, friendship, pauses and switching goals remain valid paths.
No guilt, emotional pressure, control or real-world exclusivity is used.

## Persistence and ownership

Go/Gin exposes authenticated GET/PUT
`/v1/conversations/{character}/goals`. PostgreSQL migration 9 stores:

- `config`: user-owned choices, config version and namespaced `extensions`.
- `progress`: branches keyed by relation+long-term direction, task kind or sandbox.
- independent `progress_version`: feedback does not change configuration CAS.
- shared `bond`: familiarity/trust/affection persist across task and sandbox
  switches; task/sandbox affection deltas have one quarter the relationship weight.
- `goal_turns`: account/character/request UUID idempotency ledger.

Per-account transactions share the existing commit-ordered sync feed. Every
read/write checks character access. Ownership comes from revocable sessions.
The iOS copy is a cache, not an authority. Offline edits are not misleadingly
reported as applied. Changing direction preserves other branches. Conversation
reset clears all goal progress/turn receipts, keeps explicit configuration and
increments its version so old drafts cannot resurrect state.

The AI gateway overwrites forged goal headers and forwards a bounded encoded
PG snapshot. Request JSON cannot set Python private goal attributes. Goal state
contains no service credential. The inference worker returns feedback to the
loopback Go endpoint using its private service credential; Caddy blocks
`/internal/*`, and the endpoint separately requires that credential. App session
tokens are insufficient. Cross-account service operations are not public APIs.

## Generation and feedback

Existing compact/spoken planning schemas carry bounded `goal_feedback`; its
adapter preserves the field in the public internal Plan. This is part of the
normal planning pass, not another paid model call. The speech/performance split
remains concurrent. Performance gets the goal context but chooses only declared
avatar capabilities. No new animations or body behaviour are invented here.

Feedback can adjust familiarity/trust/affection/task progress by at most 0.04
per delivered user/story turn. It must quote actual user text. Idle speech,
greetings, gestures, drafts, paused directions and duplicate request IDs do not
advance progress. Milestones are closed vocabulary, evidence-backed and deduped:
shared interest, trust opened, date agreed, repair, learning step and preference
understood. AI cannot change configuration or confirm coupling. Scores are
internal; the UI shows concrete milestones instead of a romance meter.

The worker checks config revision through the authenticated commit before
publication. A goal changed during generation rejects the stale reply. Existing
Python message storage and PG feedback are distinct transactions: same-request
retries are idempotent, but this is not a distributed atomic transaction. A
disconnect between PG commit and worker publication can leave a committed receipt
without visible delivery. Future consolidation of the AI journal into PG should
use an outbox; do not claim atomic cross-database delivery today.

Prepared reactions and quick answers include goal schema/config/progress in
their context fingerprint. New goal snapshots expire previous candidates and
cancel unclaimed work. iOS stops its active turn and preparation lease when a
saved direction changes. Consuming a prepared user answer uses the same feedback
commit path; generating it does not. Bundled first introductions remain fast and
fixed; their registration is not a relationship-progress event.

English tasks supply the language contract to spoken replies, visible thoughts,
suggestions and TTS language hints. Natural correction is meaning first, at most
one useful recast/correction per turn, with detailed grammar only when asked.
Switching away preserves task progress and follows the persona's authored
language. Generic study/listening/planning use the same character-specific voice.

## Extension and validation

Schema version 1 is additive; optional goal fields preserve older clients.
Config is at most 4 KiB and forwarded snapshots at most 16 KiB. New incompatible
behaviour requires a new protocol version; `extensions` is reserved for scoped
future fields, not a promise of zero future migration cost. Romance eligibility
is reviewed authoring policy; do not infer it from appearance or model output.

Validation uses real PostgreSQL/Redis, provider doubles for AI behaviour, and
isolated native SwiftUI tests. Tests do not call a paid provider. Document cloud
deployment, actual small provider smoke tests and device installation separately;
no model-behaviour prompt can guarantee a desired response on every turn.
