# Development checks

[README](../README.md) · [Local setup](user/local-development.md)

```sh
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest tests/unit -q
uv run python scripts/test_integration.py
```

Integration tests use real PostgreSQL and S3 in a newly named Compose project,
non-conflicting localhost ports, a test-only database/bucket/prefix, and explicit
migrations. Docker unavailability fails the command. Unit-only runs are explicit;
missing infrastructure is not silently skipped by the integration suite.

The harness removes only resources it creates on a successful run. On failure or
with `--keep`, it retains that isolated stack and logs/config under ignored `local/`.
The test fixtures refuse a database/bucket/project without test markers. Never pass
production settings to a test command. Persistent developer volumes are not test
resources and are never cleared by the harness.

Migrations are explicit: `uv run alembic upgrade head`. They are immutable after
application. API/worker startup checks the expected revision and never migrates.
Do not implement automatic destructive downgrades.

Runtime docs and examples must change with code. Architecture decisions remain in
[design](design.md); stage acceptance is in the [plan](implementation-plan.md).

## Full container lane

```sh
uv run python scripts/test_integration.py --containers
```

The harness creates a unique Compose project, test database, bucket and prefix;
it migrates, runs real integration tests, builds the image, starts API/workers,
and runs real PDF/HTML with Chromium and WeasyPrint, process-crash and two-worker
concurrency tests. WeasyPrint flow requests are checked for an explicit terminal
error; the paginated flow example runs on Chromium. Failure
retains the isolated stack and logs under local/; success removes only resources
created by that run. `--keep` retains a successful run for diagnosis. Do not run
container tests against a developer stack or while another test suite mutates it.

Deterministic unit tests cover slot filling, completion-before-wait races, empty
queue backoff and deadline servicing. Container checks also exercise real threads
and SIGTERM with a 30-second poll interval, including blocked shutdown work.
See the [worker scheduling review](reviews/2026-11-07-worker-loop.md) for the
accepted race fixes and verification scope.

The native tests cover TCP chunked intake, stalled/disconnected uploads, PostgreSQL
locking/fencing, retention and storage failure injection. Fault tests use exact
container IDs verified against the unique Compose label. They never kill a process
by a broad name match on the host. No public production test-control endpoint exists.

Kubernetes acceptance is separate: follow [the kind recipe](user/kubernetes.md).
`scripts/test_hpa.py --context kind-cardreport-test --kubeconfig local/kind-kubeconfig`
submits at most 60 synthetic reports and verifies real HPA scaling, not just schema
validity. It requires the port-forward from that recipe and Metrics Server.

[Worker configuration and timeout review](reviews/2026-11-07-configuration.md).

Unit checks require the Docker Compose CLI for configuration interpolation; no
Docker daemon or running service is needed for that check.
