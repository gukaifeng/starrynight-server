# Cache and account release — 2026-10-02

Implementation commit: `c7896089c5d26fc015527ae1a4923f57023513a9`.
Active cloud release: `20261002T041007Z-c7896089c5d2`.
Design: [prepared conversations, public identity and photos](design/prepared-cache-public-identity-2026-10-02.md).

The existing guarded upgrade tool created the pre-upgrade PG/AI backup at
`/home/starrynight/app/backups/before-api-20261002T041007Z-c7896089c5d2`,
verified release hashes, applied migration 10 and restarted the AI worker.
API readiness and AI readiness passed. Production remains the cloud endpoint;
the temporary local integration services were stopped after testing.

AI tests: 235 passed, 4 skipped. `make check`, real PostgreSQL/Redis
`make integration`, `make build` and OpenAPI generation passed. New integration
coverage includes unique immutable public numbers, UUID stability, image
normalization, owner isolation, CAS and account deletion. The two-replica local
workload is a functional check, not a production capacity benchmark.

`verify_cache_accounts.py --paid-cache` checked the actual public cloud endpoint
with disposable accounts: public number assignment, rejected renaming, photo
roundtrip, owner isolation and login identity preservation passed. Accounts were
deleted after the checks. One entry greeting was prepared with voice; background
preparation took 14.079 seconds. Consuming that ready cache returned the first
reply in 0.238 seconds and the first PCM in 0.278 seconds. This measures delivery
from the cloud to the Mac, not audible phone latency. No claim is made that a
cold, invalidated or still-generating cache is instantaneous. Quick answers and
gesture cache paths have regression coverage; paid production probes were not
repeated for every scenario.

No image generation was called. Verification captures and user data stay in
ignored `.local/`. Client 0.88.0 (118) includes public-number refresh for old
Keychain sessions, original vector defaults and authenticated photo editing;
its final signed build was installed and launched successfully on the iPhone.
