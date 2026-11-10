# Layout diagnostics review

The user authorized library/server/console diagnostics, tests, documentation and
both releases. This is an additive optional error field; old stored jobs remain
readable and are not retroactively rerendered. No database migration or new setting.

Cross-repository Claude design and implementation reviews endorsed the small
record: path/page, closed reason and optional measured geometry without report text.
The library preserves its error/rejection behavior and validates its worker JSON.
The server validates the child-produced diagnostic again in the supervisor before
storing it. Only layout_overflow carries the field. Unknown or malformed records
are dropped without changing the original failure.

The console uses text nodes, a closed reason/hint map, explicit missing values and
current-layout wording. It never presents overflow as a guaranteed resize. OpenAPI
adapts the public library dataclass rather than duplicating a separate model.

The review prompted tests for malformed/forged records at the real supervisor
seam, actual both-engine API-to-console failures, private-text exclusion and old
or partial diagnostic UI behavior. Library-only findings (private SVG paths and
NumPy scalar conversion) were fixed and regression-tested before its release.

Release order: publish CardReport 0.8.3, lock that official PyPI version, verify the
complete server suite and package, then publish Server 0.4.2. Native amd64/arm64 CI
and both renderer image smokes remain release gates. No authentication or renderer
containment policy is changed by this work.

Local acceptance used the published PyPI CardReport 0.8.3 wheel (its digest matches
the GitHub release). Ruff, formatting, mypy, 157 unit tests, 55 integration tests,
26 container tests and 48 browser tests passed. Documentation checks covered 142
local links, examples and deployment YAML; the installed-wheel console/Swagger
check passed outside the checkout. Both real renderer error screens were inspected.
The first browser run exposed an overly strict assertion that assumed bottom was
the only positive side: WeasyPrint also measured a sub-0.1 mm right excess. The
assertion now checks the bottom measurement without assuming side order; all 48
browser cases passed on repeat. Runtime detection and thresholds were unchanged.

The final restricted Claude review found no release blockers. Its optional schema
and defensive UI suggestions do not change this release contract: runtime records
remain validated by the library, OpenAPI is generated from that type, and release
CI must still pass on both native Linux architectures before publication.
