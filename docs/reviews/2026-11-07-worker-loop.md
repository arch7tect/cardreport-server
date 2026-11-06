# Worker scheduling review

Date: 2026-11-07. Scope: fill available slots without polling delays and wake the
supervisor when work finishes. No API, schema, renderer or dependency changes.

The thread pool still handles blocking I/O and process supervision. Each report
still renders in its own process. Successful claims immediately repeat the outer
supervisor loop, checking timers and shutdown before claiming another job.

A process-local `SimpleQueue` carries wake notifications, not report jobs. Only
the supervisor mutates active attempts; completion callbacks enqueue notifications.
Notifications are drained before state inspection, so a completion between state
inspection and the timed wait cannot be lost. CPython's queue operation is
[reentrant](https://docs.python.org/3.12/library/queue.html#queue.SimpleQueue.put),
which avoids taking an Event's non-reentrant wait/clear lock from a signal handler.

Empty/error claims keep a separate next-poll timestamp. Maintenance or heartbeat
activity therefore does not repeatedly query an empty queue. Completing an attempt
resets that timestamp to refill the slot. The bounded wait also services heartbeat,
lease/attempt cancellation, armed child cleanup and global shutdown deadlines.
Cancelled attempts and running maintenance cannot leave a past-due timer spinning.

Claude's initial design consultation completed successfully and supported this
approach. One concrete race was accepted: cancellation can happen before the child
exists, then the execution thread launches and stops it. That transition now wakes
the supervisor before the blocking process wait, preserving the child cleanup clock.
The suggested separate timeout helper was not needed: deterministic tests exercise
the actual supervisor loop, extracted from native startup as one private method.

The implementation review found no production blocker. Its test-validity finding
was accepted: releasing attempts immediately after SIGTERM could mask a missing
signal wake-up. The revised container test holds them blocked until the queue wait
returns after the signal. A negative control removes the stop notification and
fails specifically at that assertion. The review's stale-slot gauge observation
was also fixed by updating metrics after collection and claims.

Claude's focused follow-up confirmed that the revised test closes the blocker,
conditional on the negative control failing at the signal-wake assertion; that
condition was verified. All three consultation processes exited successfully.

Executed checks on macOS / Linux arm64 containers, Python 3.12:

- 24 unit tests passed, including deterministic filling, completion race, empty/error
  throttling, heartbeat fairness, deadline/cleanup, stop-during-claim and late-launch
  cancellation cases.
- 28 PostgreSQL/S3 integration and 20 container tests passed in the full lane,
  including real Chromium/WeasyPrint outputs, recovery, concurrency and shutdown.
- After the metrics/test refinement, all unit tests and the three real-thread and
  blocked-shutdown container cases passed again with `poll_seconds=30`.
- The flag-only stop negative control failed as expected; the production stop
  implementation passed. This checks the test's sensitivity, not throughput.
- Ruff, formatting, strict mypy and documentation/example checks passed.

No schema migration, package release or production deployment is included.

