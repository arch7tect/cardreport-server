# Worker configuration and PDF timeout review

Date: 2026-11-07. Scope: explicit execution budgets and Compose wiring, plus the
CardReport dependency's PDF timeout contract. No database migration.

## Decisions

- `RENDER_TIMEOUT` replaces the hidden clamp in the server's child. Effective PDF
  time is the smaller of the configured cap and remaining attempt budget.
- CardReport's arbitrary five-minute PDF ceiling is removed in the accompanying
  library change. Python and CLI require finite positive seconds, default 30.
  OS waits run in bounded steps under the same deadline; cleanup still owns the
  entire renderer process tree. WeasyPrint HTML keeps its existing 30-second limit.
- Server policy owns attempt, render, retry and shutdown budgets. Additional
  settings cover startup smokes, health age, DB timeouts and maintenance batches.
  S3's two SDK attempts stay fixed; I/O reserve remains heuristic headroom.
- Compose explicitly forwards all application tuning values. The four local
  connection/credential values stay routed to bundled services, preventing a
  native `.env` from injecting loopback endpoints into containers. The old
  concurrency alias remains a fallback. Settings/Compose default drift is tested.
- A compatible dependency range belongs in pyproject.toml; the deployable image
  uses the exact tested uv.lock version. No package updates happen at startup.

## Claude consultation

Two successful read-only design consultations inspected both repositories.
The first distinguished making the old cap configurable from actually removing
it; the owner then challenged the library ceiling. The follow-up agreed that the
caller owns policy and identified OS wait overflow and render-stage error mapping.

Direct `Popen.communicate(timeout=1e100)` reproduced `OverflowError` on local macOS.
The library regression verifies a short actual subprocess succeeds with the same
large deadline; another verifies repeated waits retain input/output. Export-stage
validation errors now stay in the render stage instead of reporting bad datasets.

The successful implementation review found one release-order blocker: the server
must consume the fixed library before shipping values above 300. Publication and
lockfile update are therefore prerequisites to the server push. No other code
blocker was found. Optional findings led to chunked-wait expiry/large-input tests,
a separate render-validation message, worker option-forwarding assertions and
operational notes about DB waits and shorter shutdown budgets. Compose CLI remains
required for configuration tests; silently skipping those checks would hide drift.

The large-input regression found a real POSIX issue in repeated `communicate`
calls: retrying with no input can leave partially sent stdin unwritten. The library
now uses a temporary input file only for long budgets that require repeated waits.
The ordinary pipe path is unchanged. A fourth successful focused Claude review
found no blocker in this correction. Its claim that server render time can exceed
3600 seconds was rejected: the server's whole-attempt bound remains 600 seconds.
The long-wait path serves standalone library callers.

## Verification before dependency publication

- Server: 40 unit tests, 32 PostgreSQL/S3 integration tests and 20 container tests
  passed; the container run still used the old published dependency. Ruff, format,
  strict mypy and 48 documentation links/examples passed.
- Library: a full run passed 535 tests without skips. A subsequent long-input fix
  is covered by 105 passing focused deadline, CLI, both-renderer and cleanup checks.
  Real CLI exports used a 7200-second budget with both engines and completed
  normally. Executable docs ran 51 Python blocks. The prepared 0.8.2 wheel/sdist
  passed strict metadata checks and installed-wheel checks with core and all extras.
- Release order: publish the prepared library 0.8.2 only after owner authorization,
  update the compatible dependency and exact server lock, then rerun the container
  suite with that published dependency before the server push.

## Publication and final dependency verification

The owner authorized publishing 0.8.2 and updating the server. Library commit
`b86a1b5` was published as [0.8.2](https://github.com/arch7tect/cardreport/releases/tag/v0.8.2)
and on [PyPI](https://pypi.org/project/cardreport/0.8.2/).
[Release CI](https://github.com/arch7tect/cardreport/actions/runs/42332937901)
passed 536 tests without skips, executable documentation and installed-wheel checks.
PyPI wheel/sdist hashes match the GitHub release manifest.

The server now declares `cardreport[pdf,weasyprint]>=0.8.2,<0.9`; uv.lock selects
exactly the published 0.8.2 artifacts. No unrelated dependency version changed.
With this dependency, 40 unit tests and 32 PostgreSQL/S3 integration tests passed.
All 22 container scenarios passed across the initial run and a focused correction:
five successful-report checks initially still expected the literal version 0.8.1.
They now compare reported engine metadata with the installed locked package;
all five passed on rerun. The other 17 passed initially, including real PDF child
exports with a configured 450-second render cap for both engines. These are fast
reports with a long allowed budget, not a long-running workload benchmark.

Ruff, formatting, strict mypy and 48 local documentation links/examples passed.
The isolated synthetic test stack was removed after the successful rerun; logs
remain ignored under local/. No database migration or server package release.
