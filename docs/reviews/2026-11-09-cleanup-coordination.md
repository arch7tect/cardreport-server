# Cleanup coordination review

Scope: patch release coordination of retention/orphan cleanup across workers.
No schema migration, new service, leader election, settings or retention changes.

## Decision

A worker recovers expired leases first, then attempts one database-scoped session
advisory lock for `maintain()` and one orphan scan page. A busy lock skips cleanup.
The lock lives on a dedicated autocommit connection, which closes at the end of the
cycle or on exception. This avoids a pooled-slot deadlock at `DB_POOL_SIZE=1` and
an open database transaction during S3 calls. All workers must be upgraded before
coordination is effective; older workers do not acquire this lock.

## Consultation dispositions

The initial Claude consultation completed successfully and endorsed this design.
Accepted: separate lock connection with existing connection/query timeouts;
lease recovery outside the lock; full-cycle scope; test the coordinator seam in
worker fault tests; document connection budgeting and session-pooling requirements.

The proposed fixed keepalive values were not made hidden application defaults.
Instead, operations documents the explicit PostgreSQL administrator contract and
an `ALTER ROLE` example for server-side TCP keepalives. Detection of a silent
network loss has no guaranteed deadline; keepalives do not apply to Unix sockets.
Already in-flight S3 work can finish after session loss, so deletion remains safe
to repeat. No exactly-once storage claim is made.

The lock limits concurrent cleanup, not cluster-wide cycles per interval: staggered
worker ticks may run consecutive cycles. Per-worker orphan cursors remain local;
repeated scans are possible. No shared cursor or permanent leader was added.

The final Claude consultation also exited successfully and found no release blocker.
Its optional proxy-link and idle-session timeout clarifications were added to operations.

## Verification

Five real-PostgreSQL cases cover exclusion during both retention and orphan work,
busy-skip without invoking either stage, pools with one slot, release after exceptions
in either stage, and acquisition after actual backend termination. Existing retention
and orphan tests continue to cover storage deletion and retry behavior. Worker
shutdown/wakeup tests now inject at the coordinator entry point.

Local acceptance passed 147 unit, 55 PostgreSQL/S3 integration, 26 container and
45 browser cases (273 total). Ruff, formatting, strict mypy, documentation checks
and the installed 0.4.1 wheel check also passed. Release CI repeats the complete
suite on native Linux amd64 and arm64 before publishing the tested images.

These tests do not simulate a blackholed network or certify proxy configurations.
See [operations](../user/operations.md#cleanup-coordination) for requirements and
[architecture](../architecture.md#maintenance-and-retention) for the exact lifecycle.
