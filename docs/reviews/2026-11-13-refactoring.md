# Refactoring verification — 2026-11-13

Status: implemented and verified locally; no version bump, release or deployment.
Baseline: `1c521c014c380f26319e14ccf1cd358383cd1be4`.

## Scope

Typed application-resource accessors and render-process messages, keyword Attempt
construction, shared admission/read helpers and cursor history replace repeated
code. Endpoint annotations, SQL transactions, supervision, retention and streaming
response ownership are preserved. The normal development Compose was not updated.
See [internal boundaries](../architecture.md#internal-code-boundaries).

## Checks

Host checks ran on macOS arm64/Python 3.12; container checks used Docker Desktop's
Linux arm64 environment. No Windows/amd64 execution is claimed.

- Ruff lint/format and strict mypy passed (75 source/test/check files).
- Unit tests: 161 passed, including exact storage error messages, zero-length
  originals, oversized chunks and borrowed response capacity.
- Real PostgreSQL/S3 integration tests: 55 passed.
- API/worker container tests: 28 passed, including recovery and both renderers.
- Browser tests: 50 passed, including pagination retry/reset and older list
  responses arriving after newer ones.
- `scripts/check_docs.py`: 144 local links plus template/data and deployment YAML
  checks passed before adding this record; final links were checked again.
- Installed-wheel console and Swagger checks passed outside the checkout.
- OpenAPI matched the baseline exactly as a JSON object. Canonical sorted JSON
  SHA-256: `30f02e3c4c84e65123a584bf24afda520ad08f864051ceb69cf3346a176c14f8`.
- The server child separately rendered the reference template/data with the local
  ABC-based CardReport candidate through both engines, for HTML and PDF. The full
  container suite used the unchanged published CardReport dependency in `uv.lock`.

Claude reviewed the design and actual implementation across both repositories and
found no blockers. Accessors deliberately read individual state fields, typed
process messages do not replace trust-boundary validation, and the shared read
loop preserves the callers' different limits/error codes and expiry rechecks.

The isolated test harness removed only its own stack after success. Raw reviews,
OpenAPI snapshots and check logs remain in ignored `local/refactor-2026-11-13/`.
No schema migration or deployment configuration change is required.

## PyCharm inspection follow-up

PyCharm MCP `get_file_problems` inspected all 27 Python source files and seven
JavaScript files (six console modules and the bundled Swagger asset), with
warnings included. Source rechecks resolved Python type-mismatch and optional
access findings. Typed locals replaced redundant application-state and JSON
message casts without adding runtime checks or changing partial-state access.
Explicit PostgreSQL row types, psycopg SQL/Identifier composition, response
metadata types and typed worker outcome copies retain the existing contracts.

Remaining notices are recorded rather than suppressed: `Settings()` is populated
from environment variables despite IDE missing-argument inference; SQL assistance
has no IDE data source configured. JavaScript still has weak dynamic-data/type
inference and style suggestions, plus an intentional locally caught validation
exception. This is not a claim that every IDE inspection is clean. The only
JavaScript edit in this follow-up fixes the cursor helper's JSDoc parameter lines.

Verification after these fixes: 161 unit and 55 real PostgreSQL/S3 integration
tests passed without skips, including combined archive/retention PATCH coverage.
Ruff lint/format and strict mypy (75 files) passed. OpenAPI still equals the
baseline above. Documentation links, bundled examples and deployment YAML passed.
The earlier container/browser runs were not repeated for this follow-up; the
developer Compose stack was not changed. Both bounded Claude follow-up reviews
completed successfully with no blockers. Raw results are retained in ignored
`local/ide-inspections-2026-11-13/`. No push or release was performed.
