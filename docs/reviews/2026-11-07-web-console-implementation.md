# Web console implementation review

Date: 2026-11-07. Source baseline: `ee947ce`. Scope: the five slices in the
[implementation plan](../ui-implementation-plan.md). This records source and test
verification, not a production rollout or a package release.

## Delivered behavior

The same API package/image serves `/ui/` using native browser modules and CSS.
Templates, immutable versions, JSON/YAML source import, archive/restore, submission,
shared history, status and downloads cover every existing resource API operation.
HTML preview is explicit and isolated; PDF stays download-only. Service status,
Swagger, OpenAPI and metrics remain direct operations/links. No frontend build,
new service, authentication, saved datasets or worker redesign is introduced.

History uses a shared status projection and a bounded tuple cursor independent of
the boundary row. The forward-only index migration preserves jobs and templates.
The exact schema gate still requires a coordinated drain/migrate/image upgrade.

## Review dispositions

Bounded read-only Claude reviews were requested after U1, U4 and final acceptance.
All three completed with exit 0. Raw outputs remain in ignored `local/`; this is
the sanitized decision record. The final review confirmed the U4 fixes and found
no remaining material code, security or API-coverage issue. It flagged the two
screenshot links before the images were copied into the guide; both images are now
present, visually inspected, and the documentation checker passes.

| Finding | Resolution |
| --- | --- |
| U1 history/migration contract | Reviewer found no material issue; real DB migration, pagination and query-plan checks passed |
| Failed filter refresh retained old rows/cursor | Clear both before the request; browser regressions cover templates and reports |
| Background status errors stole keyboard focus | Distinguish user refresh from background polling; regression preserves focus |
| Accepted notice was dropped and transient URL copied | Show acceptance separately with UUID/pinned version and remove URL flag |
| Popup fixture observed only the original page | Intercept at browser-context level and assert no additional pages |
| Missing workflow edge coverage | Add version pagination/reload, template error paths, real upload limit and generated markup-like text checks |

Optional additions were limited to small usability corrections: keep archive
available if a version fails to load, update the bookmark on version selection,
and warn about unsaved submission data rather than an empty template selection.
The content endpoint remains the authority on expiry; a client clock does not
change server retention semantics.

## Verification

Final local acceptance completed successfully:

| Check | Result |
| --- | --- |
| `uv run ruff check .` and `uv run ruff format --check .` | Passed |
| `uv run mypy` | Passed, 56 Python files |
| `uv run pytest tests/unit -q` | 41 passed |
| `uv run python scripts/test_integration.py --containers --ui` | 36 integration, 22 container and 30 browser tests passed in one fresh-stack run |
| `uv run python scripts/check_package.py` | Installed wheel UI/Swagger routes passed outside the source checkout |
| `uv run python scripts/check_docs.py` | Local links, all bundled examples and deployment YAML passed |
| Container `python -m cardreport_server smoke` | Chromium and WeasyPrint PDF smokes passed |
| `git diff --check` | Passed |

The final harness exited 0 and removed only its own successful test stack and
volumes. Earlier failed runs remain available locally with traces/logs; one test
interception initially missed a history URL without a query string, which was
corrected before the final run. CI runs the same browser lane and retains failure
artifacts. Checks use
synthetic bundled examples and isolated test-owned database/storage/Compose
resources. Browser screenshots in the [guide](../user/web-console.md) contain only
those examples. Desktop/narrow layout and keyboard focus were visually inspected.

The browser acceptance target is Playwright Chromium on macOS; workers run in
Linux arm64 containers locally. Other browser engines are not certified by these
tests. CSP tests prove the checked parent/storage/fetch/resource/popup restrictions,
not a universal network boundary: self-navigation remains possible, particularly
when opening an inline result directly. Only trusted library-generated HTML is
supported. Existing container tests cover both PDF engines and Chromium flow.
