# CardReport Server implementation plan

Status: reviewed implementation plan; initial and focused Claude reviews complete.
Execution authorized on 2026-11-06; all six implementation slices delivered locally.
Date: 2026-11-06. Owner: Oleg Orlov.
Baseline: [reviewed design](design.md), a uv/MIT/documentation scaffold without
runtime code, migrations, a container image or deployment manifests.

## Execution progress

- S1: foundation, pinned local dependencies and Linux arm64 PDF smoke passed.
- S2: template API and Claude review fixes verified; see the dated review record.
- S3: durable upload/status and real TCP streaming tests passed.
- S4: real PDF/HTML, 2x2 slots, Chromium crash recovery and active SIGTERM drain verified.
- S5: retry/fencing, expiry/delete grace, orphan handling, metrics and bounded shutdown delivered.
- S6: kind deployment, actual CPU HPA, enforced policy, nginx streaming, restart/replacement
  and coordinated upgrade/compatible rollback exercised.
- Final evidence and limits: [verification record](reviews/2026-11-06-verification.md).

This is a working development version, not a production certification. The recorded
checks are representative; exhaustive combinations of simultaneous storage/database
outages, every process crash point, multi-node behavior and other platforms remain
outside this local acceptance. No publication is authorized or performed.

The historical planning notes below describe the original baseline; current commands
and implemented behavior are in README and user documentation.

## Outcome and scope

Deliver a small internal service: register immutable JSON/YAML templates, submit a
reference plus streamed named datasets, obtain asynchronous status, and download
PDF/static HTML. Retain the library's public API, data limits and renderer behavior.
Use PostgreSQL for metadata/queue, S3-compatible storage for durable inputs/results,
and replaceable workers with configurable slots per pod. No authentication is added.

The first usable local result arrives at S4. Recovery/retention in S5 and Kubernetes
acceptance in S6 are required before calling the complete v1 production-ready.
No broker, Helm chart, operator, generic task engine, ORM model layer, scheduler,
custom renderer, cloned schemas, or standalone SDK. Builds before S5 are for isolated development only, not shared or long-lived
environments: orphan cleanup and queue-age enforcement are not complete.
No release/publication work is implied by this plan. Runtime work starts only when requested.

## Local development decision: Compose first, kind for acceptance

Use Docker Compose for routine development, integration tests and the full local
stack. Kubernetes is not a prerequisite for editing the API or running most tests.

| Environment | Purpose | When |
| --- | --- | --- |
| uv + Compose PostgreSQL/S3 | Fast tests, migrations, API debugging in PyCharm | S1 onward |
| Full Compose API + worker containers + PostgreSQL/S3 | Real Chromium, end-to-end reports, crashes, concurrency | S4 onward |
| Disposable kind cluster | Kubernetes manifests, pod replacement, shutdown, CPU HPA | S6 |

Use one compose.yaml. PostgreSQL and an S3 service are ordinary services; the app
profile adds migration/API/worker services as their code becomes available. The
worker has no fixed container_name or published host port so Compose can scale it.
Named volumes preserve local developer state. Bind published ports to 127.0.0.1;
make their host port values configurable, so a test project never collides with an
already running developer stack. Container-based tests can omit host bindings;
DB/S3 credentials are development-only and documented in .env.example. Keep actual
local configuration ignored. There is no authentication at the report API layer;
that does not mean exposing the database or storage without their credentials.

Choose a single-node SeaweedFS container for local S3, with a pinned release and
image digest verified in S1 (no floating latest). Its upstream quickstart provides
an all-in-one S3 mode. Do not deploy its distributed topology or admin console here.
This is a local test dependency, not a production-storage recommendation. The
adapter continues using ordinary boto3 S3 operations. Verify exactly PutObject,
GetObject, HeadObject, paginated ListObjectsV2, DeleteObject and bucket initialization
with the actual pinned server. MinIO is not the default: its upstream community
repository currently states it is no longer maintained/source-only.

Provide two documented routes:

1. Dependencies in Compose, API under uv/PyCharm against localhost endpoints.
   Prefer a worker container for PDF/debug integration; both see the same DB/S3.
   Native worker execution is not supported in v1: the hard cleanup contract requires
   a container runtime. Debug API code natively and worker code inside its container.
2. Everything in Compose, using the same Linux app image as deployment. Dependency
   healthchecks and a successful explicit migration step precede API/worker startup.
   Run application retries after startup too; depends_on does not handle outages.

Planned command shape, to become executable with the relevant slices:

```sh
# S1: dependencies and developer checks
uv sync --locked
docker compose up -d --wait postgres s3
uv run alembic upgrade head

# S4: explicit migration, then the complete containerized service
# Build the shared app image before the first migration on a fresh checkout.
docker compose --profile app build
docker compose --profile app run --rm migrate
docker compose --profile app up -d --wait api worker

# More worker containers; WORKER_CONCURRENCY remains a separate setting.
docker compose --profile app up -d --scale worker=2 worker
```

These are planned interfaces, not runnable commands in the current scaffold.
At implementation, verify each command from a fresh checkout. Document stop/restart
without deleting volumes. Test runners use their own Compose project name, test DB and bucket prefix, with
non-conflicting ports or container-only endpoints. Before any destructive test,
require both a test-marked DB name and bucket/prefix, plus the expected isolated
Compose project; refuse to run on missing/mismatched markers. Container-kill tests
resolve exact IDs by Compose project/service labels, never by service name alone.
Any test resource removal is restricted to resources created by that test run;
retain failure evidence separately. Never clean developer or production data. Resetting developer
volumes requires explicit user action; do not put destructive cleanup in quickstart.

On 2026-11-06, Docker client/Compose/kind/kubectl were present locally; the Docker
daemon was unavailable. No containers or clusters have been launched for this plan.
Image availability, architecture support and resources must be verified in S1.

## S1 — Foundation and a repeatable local environment

Deliver:

- src layout, settings, API health entry point, declared/locked runtime dependencies;
  exact tested CardReport version, Ruff, strict mypy, pytest and httpx test tooling.
- compose.yaml with pinned PostgreSQL and single-node S3, bounded readiness checks,
  local-only ports, named volumes and explicit bucket bootstrap. Share this stack
  with integration tests; do not add Testcontainers as a second orchestration layer.
- A single app Dockerfile using uv lock, installed Chromium/fonts and an init
  process. Initially smoke-test dependency import and real PDF rendering; do not
  invent a placeholder worker just to fill the Compose profile.
- Alembic migrations using explicit SQL, psycopg application queries and pools;
  no SQLAlchemy ORM models. One migration command/process, not per-worker migration.
  API/worker startup must reject a DB revision outside their explicitly supported
  revisions (initially the exact expected Alembic revision); readiness cannot pass
  and workers must not claim. Only the explicit migrate command changes the schema.
  Applied migrations are immutable and forward-only. Use uv run alembic until the
  container migrate entry point is available.
- A minimal CI definition for lock/lint/types/tests; activate integration jobs as
  their paths exist. Do not create a remote or publish an image as part of this slice.

Tests and acceptance:

- Settings enforce bounds/relationships; invalid DSNs/config fail clearly without
  logging secrets. Liveness is process-only; API readiness checks dependencies.
- Migrations apply to a fresh real PostgreSQL database; a repeated upgrade is a
  no-op. Migration failure prevents startup. Keep migration integration isolated.
- Actual S3 put/get/head/list/delete round trip; pagination and absent-object handling. Verify S3 accepts configured credentials
  and rejects missing/invalid ones; do not accidentally run anonymous storage.
- The app image runs as intended with fonts and a real CardReport PDF. Record tested
  host/container architecture. Test arm64/amd64 only where actually available.
- Compose healthchecks/readiness use tools present in their images and bounded
  retries, not arbitrary sleeps. Docker unavailability is a clear prerequisite
  failure when integration tests are requested, not a silently passing skip.

Documentation: README installation/status, docs/user/local-development.md and
configuration basics, .env.example, docs/development.md with exact commands and
separate unit/integration selection. Versions and runtime assumptions are recorded.

Exit: another developer can start dependencies and pass integration checks using
only the documented procedure; the container can render one small PDF.

## S2 — Immutable template management

Deliver the template routes from design section 4, canonical JSON storage, digest,
version allocation and archive/unarchive. Validate through ReportTemplate only.
Add required tables/indexes through migrations. Implement schema-derived OpenAPI
metadata (including namespaced $defs/$refs) and locally bundled Swagger assets.
Do not duplicate the CardReport transport model with hand-maintained Pydantic fields.

Tests and acceptance:

- JSON/YAML equivalent templates register; bad/duplicate keys, unknown format,
  oversized input, wrong media/encoding and invalid bindings fail synchronously.
- Real concurrent PostgreSQL transactions allocate distinct monotonic versions;
  existing definitions are immutable. Admission/archive races are covered in S3.
- List pagination has stable ordering; unknown IDs/versions and archived mutations
  follow the documented status/error contract.
- /openapi.json resolves all local references; examples validate against CardReport's
  original schema. /docs and its assets work without external network access.

Documentation: template lifecycle/API reference, registration examples and explicit
version-pinning advice. Do not yet present generation routes as available.

Exit: templates can be managed through HTTP and Swagger with real persistence.

## S3 — Durable submission and status

Deliver raw Request streaming -> byte-counted/hashable spool -> single S3 PutObject
-> queued job transaction. Implement data/media/header limits, upload semaphore,
soft backlog limit, admission-time template snapshot and GET status. Close DB
transactions before network work. Include claim-ready indexes and retention fields.
There is no worker yet: queued is an honest intermediate milestone, not a demo PDF.

Tests and acceptance:

- JSON and YAML preserve bytes. Use a real TCP HTTP server/client for chunked input,
  unknown Content-Length, slow chunks, disconnect and timeout; ASGI mocks alone
  cannot establish streaming behavior. Verify incremental consumption/backpressure.
- Oversize declared and actual bodies are rejected; compressed/unsupported bodies
  fail; partial uploads create no runnable jobs and temporary files are removed.
- Block admission before reading when possible; bounded semaphore returns 429,
  dependencies return 503. Exercise the documented soft backlog overshoot policy.
- 202 is sent only after durable object plus job commit. Inject failure after object
  upload/before DB commit and after commit/before response; assert orphan versus
  durable job outcomes. Never auto-retry a submission with uncertain acceptance.
- Latest version is resolved before upload; an intervening archive/new version does
  not change that accepted snapshot. Unknown/archived references reject new admission.
- Malformed dataset body is durably accepted here and will fail validation in S4;
  document that 202 does not assert input validity or layout correctness.

Documentation: streaming client using file iteration, query/options/media contract,
202/status/error semantics and duplicate-job possibility on retries. OpenAPI data
body comes from the library schema; it documents, not validates, the raw request.
Starting in S3, migration tests upgrade the previous slice's schema with real rows
and verify data preservation and compatibility errors, not just fresh databases.

Exit: bounded streamed data reliably produces a recoverable queued job/status URL.

## S4 — A complete local report through bounded workers

Deliver supervisor/child execution, FIFO eligible claims with attempt tokens/leases,
heartbeat and conditional result commit, dependency startup smoke, bounded slots,
real rendering, status and streamed download. Basic stale-owner fencing is required
now, not retrofitted after adding concurrency. Include a minimal expired-lease
reaper in locked transactions: requeue recoverable attempts or fail at the attempt
cap. Hard-stop and neighbouring jobs must recover in this same slice. Add worker/API
Compose app services; hard-fallback recycling exits non-zero, normal completed
SIGTERM drain exits zero. The worker uses restart: on-failure and a bounded healthcheck of
supervisor progress/startup completion, so Compose --wait has a meaningful signal.
API/worker depend on healthy DB/storage, not a Compose migrate service dependency:
the documented migrate invocation is explicit, and startup revision checks reject
a missing migration. Ordinary up/restarts must not run migrations implicitly.

Supervisor owns DB/S3 and downloads inputs; children get files and an allowlisted
environment, decode/bind/render, and write outputs. Normal PDF deadlines use library
cleanup first. Include graceful child unwind and the whole-container hard-stop
fallback in this slice; a crashing job may interrupt other slots. No reusable process
pool, no per-job Kubernetes Job, no arbitrary code or extra report parameters.
Run workers only in containers. Keep the default per-container PID namespace in
Kubernetes, not shareProcessNamespace. Use a dedicated, unshared worker temporary root (container filesystem/tmpfs in Compose,
per-pod emptyDir in Kubernetes, never a volume shared by scaled workers): remove
only service-owned temporary leftovers at startup and each attempt's temporary
files on success/failure/timeout. Never remove shared inputs/results or user paths.
An emptyDir can survive container restart in the same pod, so this is required.

Tests and acceptance:

- Complete register -> submit -> poll -> download for JSON/YAML and PDF/HTML against
  actual DB/S3/Chromium. Download headers/types/hash/size match the committed object.
- Reuse public/synthetic fixtures for the original CardReport reference report and
  one long-table flow report. Verify selectable PDF text, page count and every table
  row exactly once; visually inspect representative outputs, not byte-identical PDFs.
- Data/type/cardinality/binding failures, genuine PDF overflow, unsupported features,
  expired/too-large render budget and oversized output yield safe terminal errors.
  HTML success promises semantic validation/preview, not browser geometry validation.
- Two containers with at least two slots each make progress; use controlled barriers
  to prove actual concurrent attempts and the configured per-worker bound. A stale
  token cannot heartbeat or commit, including after lease expiry before reclamation.
- Force the hard fallback with real detached Chromium descendants: none survive
  container termination, the Compose worker restarts, and interrupted neighbours
  are reclaimed or fail at their individual caps. Verify temporary-file cleanup
  on normal completion/failure/timeout and container startup.
- Children do not inherit DB/storage credentials. Public error bodies/logging rules
  do not reveal dataset values or exception tracebacks. CORS is disabled by default. Renderer smoke failure
  disables claims instead of consuming the queue.
- Slow/aborted downloads release resources and obey timeout; failed/non-ready IDs
  cannot expose partial objects. Status is readable independently of rendering.

Documentation: working Python/curl quickstart, API reference and downloadable public
examples; local full-stack and PyCharm API workflows; renderer limitations and error
recipes. Commands must be run against the fresh full Compose stack.

Exit: a user can generate and inspect both reference and flow reports locally using
only README/user docs. This is the first useful development version, not v1 completion.

## S5 — Recovery, retention and meaningful operational checks

Extend the minimal S4 reaper with full retry/backoff policy, maximum queue age, safe cleanup
of inputs/results/orphans, result expiry, metrics and completed shutdown/drain behavior.
Use the existing maintenance loop and bounded batches; no scheduler service.
Deliver an operator setting to pause new report admission and template mutations
with 503 while allowing status/download reads. Document applying it to every API
replica, waiting for admitted uploads and accepted jobs to drain, and only then
upgrading engines/schema. No admin API is needed for the setting.

Tests and acceptance (real DB/storage where semantics matter):

- Kill a worker after claim, during rendering, after upload, and before completion
  commit; another worker reclaims it and only one result pointer wins. Inject stale
  completions, expired-heartbeat attempts and concurrent reapers deterministically.
- Simulate DB/S3 outages during heartbeat/upload/commit; stop ownership promptly,
  classify transient versus terminal failures, enforce bounded retries. Independently
  count attempts for neighbouring jobs interrupted by the same container failure.
- SIGTERM drains within grace. Extend the S4 hard-fallback check to concurrent failures/lease outages; actual
  detached Chromium cleanup and neighbour reclamation must already pass in S4.
- Maximum queue age is from original creation; a requeue does not reset it. A full
  worker stops claiming, and a blocking child does not block heartbeats.
- Expiry uses the designed clock/deadline rules. Test expiry before headers versus a
  download already open; retain bytes until bounded downloads can finish. Test failed
  deletes, orphan prefix pages and delayed writes, preserving live inputs/winning outputs.
- Test-only IDs/prefixes isolate cleanup. Advance test clocks/DB timestamps rather
  than waiting hours or adding a public test-control endpoint.
- Metrics have bounded labels; job IDs/data/text stay out. Document CPU requests and
  how queue/active-slot metrics are aggregated without multiplying a global count.

Documentation: operations, status/error/retry table, retention, drain/upgrade/rollback
procedure and diagnosis. Record a small workload matrix (reference, table, dense
chart) with input/output sizes, PDF time, peak memory and concurrency; choose default
resource settings from measurements, not arbitrary latency promises.

Exit: crash, stale-owner, timeout and cleanup tests pass in Compose; the documented
failure/recovery behavior is demonstrated and safe to take to Kubernetes acceptance.

## S6 — Kubernetes acceptance and final delivery checks

Deliver plain Kubernetes manifests for API/worker Deployments, Services, configuration,
probes, resource limits/requests, temporary storage, network policies and CPU HPA.
Use a small kind-only dependency overlay for disposable PostgreSQL/S3; do not run
stateful dev services this way in production. No Helm, operator, GitOps or cluster
provisioning framework. Explicit kubectl context/namespace for every test command.

kind is a release/deployment acceptance lane, not mandatory for every code edit.
Use the same app image, load it into kind, install a pinned Metrics Server with the
local prerequisites documented, and run a bounded workload. Start with one node;
this verifies pod/container behavior, not multi-node resilience or production sizing.

Tests and acceptance:

- Apply/migrate/smoke in a fresh cluster; API and workers use the same engine build.
  Verify direct and proxied HTTP streaming using the intended ingress implementation;
  port-forward alone cannot validate proxy buffering. Keep ingress setup optional
  for daily work but required before claiming that deployment route is verified.
- Verify worker replacement, grace-period shutdown, shared storage and two replicas
  with configurable slots. Force a worker container restart inside the same pod
  and prove service-owned temporary leftovers are cleared without touching durable
  inputs/results. CPU HPA must actually obtain metrics and change replicas
  under sustained bounded load; merely parsing an HPA manifest is insufficient.
- Do not assume default kind networking enforces NetworkPolicy. Use a policy-capable
  CNI for the policy test or run that test in a suitable isolated target cluster;
  mark enforcement unverified otherwise. Do not treat a default kind pass as proof.
- Render the reference/flow examples through the deployed API, verify contents, and
  exercise admission pause/drain/coordinated engine upgrade plus rollback.
- Validate only the test cluster namespace. Never reuse the current kubectl context
  implicitly, wipe another cluster, or delete developer volumes as test cleanup.

Documentation: internal Kubernetes deployment/upgrade guide, kind acceptance recipe,
configuration/limits, tested versions/architectures and remaining verification limits.
README leads to Python client quickstart; CLI/operations are separate sections.

Exit: all required integration, failure and deployment checks pass; final Claude
review of implementation/tests/docs has no unresolved critical finding. Record
unverified platform/storage claims honestly. Publication still needs a separate request.

## Verification and review policy

- Unit tests: small pure decisions such as settings, error mapping, deadlines and
  OpenAPI reference rewriting. Do not write tests for scaffold-file existence.
- Integration tests: real PostgreSQL transactions and an actual S3 endpoint. Mock
  only failure injection, never use SQLite/in-memory queues to prove locking.
- Container tests: real Chromium and whole-container termination; API async tests
  alone cannot establish process cleanup or memory behavior.
- Kubernetes tests: kind/isolated cluster for the deployment-specific properties.
  The Compose suite stays the everyday and default CI route.
- Add Ruff, strict mypy, pytest and doc-link/example validation with the first code.
  CI fails when a required integration environment is missing; fast unit-only runs
  are an explicit separate command. No duplicate library regression suite.
- Every slice updates user docs and its relevant tests before completion. Execute
  registration, streaming submission, status and download examples as a shared
  smoke scenario; link checking alone does not verify code examples.
- Obtain bounded read-only Claude review at S2 (API/persistence), S4 (working path),
  S5 (failure/recovery) and S6 (final integration). Resolve confirmed findings and
  rerun affected checks; do not rerun the entire suite repeatedly without cause.
- Save a short dated verification/review record with versions and command outcomes.
  Raw logs/reports remain ignored in local/ or output/; only synthetic fixtures enter Git.
- Before a service upgrade, keep the previous image and verify migration compatibility.
  Initial migrations are additive, but that alone does not make an older image pass
  an exact revision gate. Test the rollback image against the actual DB revision.
  If incompatible, keep admission paused and use a forward fix or an explicitly
  approved offline backup restoration plan; no automatic destructive downgrade or
  silent bypass of schema checks. Document this before S6 upgrade acceptance.

## Sources and planning verification

- [Compose dependency readiness](https://docs.docker.com/compose/how-tos/startup-order/).
- [Compose profiles](https://docs.docker.com/compose/how-tos/profiles/).
- [kind quick start and image loading](https://kind.sigs.k8s.io/docs/user/quick-start/).
- [SeaweedFS single-node S3 quickstart](https://github.com/seaweedfs/seaweedfs#quick-start).
- [MinIO upstream maintenance status](https://github.com/minio/minio).

These sources inform the local-environment choice; they do not establish that any
pinned image or this project's stack has been tested. Exact images are selected and
verified in S1. [Claude plan review](reviews/2026-11-06-implementation-plan.md).
