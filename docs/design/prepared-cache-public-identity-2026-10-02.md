# Prepared conversations, public identity and photos

The goal release introduced a cache regression: a fingerprint included both the
request goal snapshot and the most recent stored snapshot. Publishing progress
did not synchronize the source request used by refill. A new gateway request
could therefore invalidate work prepared for the same newly committed direction.
An entry-only prediction also replaced the active role and cancelled its jobs.

The fingerprint now uses one monotonically reconciled authenticated snapshot.
Committed feedback is copied into the refill request and worker snapshot before
the next draft. Older in-flight headers cannot roll the snapshot backward.
Actual goal/history/voice/choice changes still invalidate stale candidates.
Entry-only preparation preserves active-role jobs. Four background slots are
bounded and priority-queued: quick answer, entry greeting, gestures, then idle.
Ready text, performance and PCM playback does not enter that queue or regenerate
content. In-flight candidates still hand their stream to the real trigger.
One candidate per eligible scenario/choice remains the configured limit.

## Public identity

Migration 10 adds `users.starry_id`: `XY` followed by 12 digits, allocated by a
noncycling database sequence starting at 100000000001, with a unique constraint.
Existing users receive numbers without changing UUIDs or ownership foreign keys.
UUID stays the permanent authentication/storage key. Login name is independent.
Neither profile PATCH nor direct SQL UPDATE can change the public number today.

`account_handles` reserves assigned aliases; deleting an account removes its UUID
link but does not make a used number available to someone else. A future rename
requires a dedicated authenticated, audited transaction, a new format/policy if
needed, retirement of the previous alias and a new current alias. It must never
re-key conversations or sessions. That endpoint is deliberately not enabled now.
Sequence exhaustion is an error rather than wrapping to an existing identifier.

## Profile photos

Default `starry-cat-v1` is original client-rendered vector art, with moon bunny
and little planet alternatives. Old explicitly selected symbols remain valid.
Missing/server-default moon avatars are migrated; authored character art is not
changed and no image generation API is invoked.

Authenticated PUT/GET `/v1/me/avatar` normalize owned JPEG/PNG uploads to a centered
256px JPEG. Input is bounded to 512 KiB and 4 megapixels; output to 128 KiB. The
server strips source metadata by re-encoding, verifies format/dimensions and uses
Go's official `x/image/draw` scaler. Upload bytes and the profile reference commit
atomically with profile CAS and the account change feed. Profile PATCH cannot
reference another account's upload. Requests do not fetch arbitrary URLs.

Small canonical photos are stored one per user in PostgreSQL bytea, privately,
independently of unconfigured OSS model delivery. This bounded starter storage
does not apply to large character binaries. Future object storage can preserve
the hash/reference contract while replacing the blob backend. User deletion
cascades photo removal; backup retention remains governed by the server runbook.

iOS uses Apple's PhotosPicker and processes/downsamples outside the UI thread.
The profile reference follows the account sync feed; the image cache is keyed by
internal account UUID and SHA-256, verified before use, and survives restart for
offline display. Photos are never mixed between accounts or sent to AI providers.
Public avatar delivery for author pages is a separate future privacy decision;
this endpoint exposes only the requesting user's photo.

## Validation

Regression tests cover progress-to-cache reconciliation, stale header rejection,
ready quick answers without extra generation, entry prediction preserving active
jobs and priority/cancellation capacity. Go integration tests use real PG/Redis
for handles, CAS, canonical photos, owner isolation and deletion. Provider doubles
do not invoke paid models. `verify_cache_accounts.py --paid-cache` is an explicit
disposable-account probe for one prepared entry with voice, reporting first reply
and first PCM timing; it does not claim every cold or unavailable event is instant.

Official references: [Apple PhotosPicker](https://developer.apple.com/documentation/photokit/bringing-photos-picker-to-your-swiftui-app),
[Go x/image/draw](https://pkg.go.dev/golang.org/x/image/draw).
