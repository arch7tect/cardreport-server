# Dual renderer review

Date: 2026-11-07. Scope: per-job Chromium and SVG/WeasyPrint selection in the server.

The owner requested both engines. The implementation uses CardReport 0.8.1's
public renderer API, a closed query enum, a persisted job field and one worker
image containing both runtimes. No library changes or renderer plugin framework.

Claude completed a read-only review of both repositories (exit 0), including
submission/queue/child rendering, startup and cleanup, migration, container,
tests and documentation. No blocking source defect was found. Dispositions:

- Accepted: make the startup smoke KPI an explicit 50 mm row; natural-height KPI
  cards are not a reliable WeasyPrint geometry fixture. The initial container
  smoke reproduced this layout failure; the explicit row is the corrected fixture.
- Accepted: document WeasyPrint HTML's fixed 30-second library timeout and the
  outer supervisor deadline. Raising the attempt budget does not extend that
  HTML timeout. PDF receives the remaining bounded attempt budget.
- Accepted: renderer dependency failures stop all claims, not just browser failures;
  update schema history through revision 0005.
- Confirmed: retries retain renderer selection, unknown names fail before upload,
  unsupported WeasyPrint flow is terminal without fallback, and both engines use
  the existing library subprocess cleanup under the container boundary.
- Upgrade constraint: stop old workers before applying 0005. Already-running old
  workers do not learn the new field; startup revision checks cannot replace a
  coordinated drain/stop/migrate/start operation.

A direct library call confirmed that forcing the 150-row flow fixture into a
WeasyPrint dashboard raises `RenderError` (internal `AssertionError`), rather than
`LayoutOverflowError`. The server retains its safe `render_failed` outcome;
there is no fallback or successful partial output. This pinned-library limitation
is documented and covered separately from a small-card layout-overflow test.

Claude's focused follow-up completed (exit 0) and found this safe failure mapping
non-blocking. Its requested documentation note about oversized content was added.

Verification on macOS host / Linux arm64 containers, Python 3.12:

- Ruff check/format, strict mypy (40 files), locked dependencies and local docs/
  bundled examples passed.
- 14 unit tests and 28 real PostgreSQL/S3 integration tests passed, including
  migration defaults, renderer enum/OpenAPI, persistence and retry selection.
- 19 container cases verified: reference PDF/HTML with both engines, Chromium
  flow pagination, WeasyPrint flow rejection, output/deadline/layout limits,
  process crash recovery, concurrency and shutdown bounds. The full lane passed
  17 cases before the oversized-table expectation was separated; all 7 child-limit
  cases then passed, including the corrected fixture and the added regression.
- Both real PDF startup smokes passed in the rebuilt image.

The failure traces remain in ignored local evidence. The existing library is not
patched or republished by this change. This is source publication,
not a package release or a production rollout. Earlier kind/HPA evidence applies
to the initial implementation; this change is checked in the Compose/container lane.
