# Web console implementation plan

Status: U1–U5 complete. Implementation and final acceptance reviewed with Claude.
The [implementation verification](reviews/2026-11-07-web-console-implementation.md)
records actual checks and resolved findings.
Owner: Oleg Orlov. Date: 2026-11-07.
Contract: [web console design](ui-design.md).
[Review and verification record](reviews/2026-11-07-web-console.md). Keep the existing
[architecture](architecture.md), worker lifecycle and library validation unchanged.

## Delivery approach

Five ordered slices, each with a reviewable working result, focused tests and its
user/developer documentation. Use ordinary browser modules and existing Python
service modules. No frontend build pipeline, API client generator, custom component
framework or new infrastructure. Resolve review findings before expanding scope.
An API coverage checklist in the user guide maps every resource operation to its
screen; links cover Swagger, OpenAPI and raw metrics.

This plan authorizes no runtime execution, deployment or release by itself. After
implementation is requested, work through the slices without routine permission
questions; source publication/release follows the owner's explicit scope.

## U1 — Report history contract and persistence

Implement the additive GET report-list endpoint, typed query validation, bounded
opaque cursor and shared status projection described in the design. Add the two
history indexes through the next migration, updating the expected schema gate.
Do not alter report state transitions, retention or the existing status response.

Verification:

- Real PostgreSQL tests for no rows, default/explicit limit, template/state filters,
  archived/unknown templates and safe field allowlist.
- Deterministic equal timestamps and different microseconds/UUIDs: walk multiple
  pages and check ordering, no duplicates and no missing static fixture rows.
- Delete the boundary row between pages; continuation still works. Insert newer
  rows and change states between requests; verify/document live-view semantics.
- Reject malformed, oversized, invalid-date/UUID and unsupported-version cursors;
  unknown states, invalid slugs and out-of-range limits return 422.
- Upgrade the previous schema with existing queued/terminal jobs and templates;
  preserve data, check indexes and repeated migration. Retain incompatible-image
  startup rejection; test no destructive downgrade path is introduced.
- Inspect representative query plans with a synthetic retained history. Avoid
  asserting a tiny-table planner must use an index; add state indexes only if the
  measured query requires them.

Documentation: update HTTP API list/cursor semantics, history visibility and
upgrade notes. Keep new UI user instructions marked forthcoming until U2.

Exit: callers can browse retained reports independently of any browser state;
existing submit/status/download tests pass.

## U2 — Packaged console and complete template workflow

Add `/ui/` and static modules/styles, hash navigation, common API/error handling,
service-status panel and links. Implement template lists/detail/version pagination,
JSON/YAML import/paste, create/new version, archive/restore and canonical JSON
copy/download. Use textarea editing, no code-editor package.

Verification:

- Shell redirect, correct asset MIME types, missing-asset 404, security/cache
  headers, no alternate shell route through Swagger static files, and no API-route
  shadowing. `/docs` still works without network access.
- Establish the browser harness here, before tests need it: add an explicit `--ui`
  option requiring `--containers` to the existing isolated Compose runner, local
  Python Playwright sync_api fixtures and a direct dev dependency locked in uv.lock.
  Run browser tests after existing fault tests, against a verified ready stack.
  Reuse its per-run database/bucket/ports and cleanup/retention behavior.
- Enable this lane in CI now, installing its matching browser with
  `uv run playwright install --with-deps chromium`. Missing browser prerequisites
  fail rather than skip. No pytest plugin or Node toolchain is required.
  Prove the shell loads with external network requests blocked.
- Test template JSON and YAML creation, version selection beyond page one,
  validation location, archived conflict, archive/restore, and actual returned
  version after a concurrent append.
- Test keyboard focus/labels, navigation/hash reload, safe rendering of source and
  errors, unsaved-text protection and retained draft after failed save.
- Build/install a wheel outside the source checkout and verify UI files and routes
  exist; verify the container-served shell too. No Node required in either path.

Documentation: create `docs/user/web-console.md` with template workflow and YAML
normalization note; add README navigation and native/Compose UI URLs. Update
`docs/development.md` with browser installation and focused test commands.

Exit: a user can manage every template API operation in the packaged console.

## U3 — Submission, history and job detail

Add data file/paste input, explicit formats, renderer/output selection, pinned or
latest version, one-shot submission and real status transitions. Connect history
filters/pagination and bookmarkable detail to U1. Add adaptive detail polling,
visibility/navigation cleanup and manual refresh. Use the existing file body
transport; do not parse dataset files or add multipart upload.

Verification:

- Browser against real isolated stack: register, choose exact version, upload JSON
  and YAML, get 202, poll and download. Verify both renderers with dashboard data
  and Chromium flow; retain the existing unsupported-WeasyPrint-flow behavior.
- Compare bytes/hash of file input received by the backend with the synthetic
  source, including UTF-8, using direct test-only DB reads for input_hash; do not
  add a public raw-data endpoint for the assertion. Test paste separately.
- Simulate lost response after accepted POST: one submission only, draft retained,
  ambiguous-acceptance message and history link. Double click creates one request.
  Cover 413, 415, 422, 429/Retry-After and 503 without retrying mutations. Also
  exercise a real over-limit upload: an early response may appear as a browser
  network error, which must retain the same uncertain-acceptance behavior.
- Deterministic intercepted GET responses cover queued/running/queued retry,
  failure, expiry, missing metadata, stale fetch results and recovery after an
  outage. Verify one poll in flight, pause on hidden tabs and stop on navigation.
- Verify all versions/templates are selectable beyond their first pages; filter
  changes reset report cursors and refreshing does not erase form inputs.
- A second independent browser context sees jobs created by API or another client;
  no localStorage history or stored dataset is required.

Documentation: complete the console generation/history guide, explain 202,
uncertain submission, shared history, retention and manual data reselection.
Do not imply cancellation, input retrieval or server-side rerun exists.

Exit: users can follow template -> generation -> real status -> download using
only the console, with preserved API failure semantics.

## U4 — Safe result preview

Add optional content disposition while preserving attachment defaults and stream
handling. Embed HTML through its HTTP URL and sandbox/CSP from the design; verify
actual Plotly rendering. PDF stays download-only; reject inline PDF explicitly.
Keep preview explicit/on demand, not one frame per history row.

Verification:

- API tests for default attachment, inline HTML, unsupported inline PDF, invalid
  disposition, MIME/filename, cache/security headers, original byte/hash identity, 409/410/404 and expiry
  between lookup and S3 open. Reuse existing disconnect/timeout coverage.
- Real browser previews for Chromium HTML with visible chart marks and WeasyPrint
  SVG; checking only a frame load event is insufficient. Block external network.
- Synthetic HTML security fixture served through the real preview endpoint attempts
  parent DOM/storage access, API fetch and remote image/script requests. Verify
  those accesses are blocked, console remains intact and CSP restrictions hold.
  Separately test frame self-navigation to a harmless local canary: record the
  remaining navigation risk without claiming all network requests are blocked.
  Test direct preview entry as well as embedding; the embedded frame must not
  navigate its parent/top or open popups. Also test markup-like template/data text
  rendered by CardReport. Do not add a test-only production endpoint.
- Verify shell CSP does not break child chart scripts, default attachment policy
  stays unchanged, and no report text becomes console DOM markup.
- Download valid PDFs from both engines and inspect text/page expectations already
  used by container fixtures. Verify that PDF has an explicit Download action
  and does not create a broken sandboxed PDF frame.

Documentation: preview vs checked PDF, PDF download-only scope, safe JSON errors
from preview expiry races and the internal-network boundary. Update API disposition/header reference and security
notes; add synthetic screenshots for a template detail and completed report.

Exit: HTML preview displays actual charts without granting report scripts access
to the application. Default download callers retain their behavior.

## U5 — Full checks, documentation and final review

Use the browser/CI lane established in U2 for the final acceptance run. Do not
create a second stack runner or parallel fault-injection system. Confirm all
prerequisites fail clearly and successful cleanup affects only this run's resources.

Complete commands and acceptance:

- Ruff, formatting, strict Python mypy, unit and real DB/S3 integration checks.
- Existing container lifecycle suite plus the new browser suite, using real
  Chromium/WeasyPrint workers. One final complete run after focused fixes.
- Package/wheel and container static-asset verification; offline shell/Swagger
  assets, no external fonts/CDNs. Capture browser console failures and traces on
  failed tests under the run's ignored local directory; add CI failure artifacts.
- Documentation links/examples, new API examples and UI route instructions.
- Manual desktop/narrow-screen and keyboard review; screenshots use synthetic data
  only. Record tested browsers/platforms, not assumed cross-browser support.
- Cross-check the design API-coverage table against the implemented screens and
  existing OpenAPI for resource operations and the actual routes for health,
  metrics and docs, which are excluded from OpenAPI. These links need not become
  dashboard features.

Update README, user API/console/local-development guides, operations upgrade notes,
architecture and developer checks. Mark delivered plan slices and record actual
commands/results in a dated verification note. Planning documents remain proposals
until implemented; do not advertise `/ui/` as available before it ships.

Obtain bounded read-only Claude reviews after U1 (contract/migration), after U4
(browser boundaries and workflows), and at U5 (final diff/tests/docs). Resolve
confirmed material findings and rerun affected checks; do not add speculative
features to satisfy optional suggestions. Source push/package release/deployment
are separate from implementation and occur only within owner authorization.

Exit: full API coverage, tested package/container delivery and readable user docs;
no unresolved material review findings. A previous image is not assumed to work
with the new schema: document the existing drain/migrate/compatible-image rule.
