# Resource budgets and image-enabled templates

The owner authorized library/server release and a local Compose upgrade after
review and verification. The service adopts CardReport's public Image/template
asset support; no asset registry or separate upload service is added.

Restricted Claude consultations covered both real repositories. Accepted findings
led to saved admission resource policies, independent preview limits, raw downloads
verified to a temporary file, preserved file diagnostics above former input caps,
and early rejection of a stored template exceeding a lowered current budget.
Library fixes cover YAML alias expansion and sample table validation. A follow-up
JSONB storage concern was disproved by migration 0003 and a real PostgreSQL test
at the exact canonical byte limit; Claude subsequently withdrew that blocker.

Migration 0009 preserves existing rows and adds a nullable resource policy. Legacy
rows restore the old input/template/snapshot maxima and 128 MiB historical output
maximum. Templates do not control resource settings. Preview limits remain current
operator controls; accepted generation budgets remain attached to the report.

Final local verification uses the public PyPI CardReport 0.10.0 lock, without a
local dependency override: 164 unit, 59 PostgreSQL/S3 integration, 33 container and
52 browser checks passed (308 total). Coverage includes changed settings between
admission and claim, retained inspection/downloads, preview rejection with raw
access, exact-budget stored templates, logos in both PDF engines and worker recovery.
The first container/browser runs exposed stale direct-child test messages and a
JavaScript syntax error; both were corrected and the affected full suites passed.
Ruff, formatting, strict mypy, 163 documentation links/fixtures and the installed
wheel console/Swagger check passed. All 12 existing local template revisions
validate against the target library. The release workflow repeats validation on
native Linux amd64 and arm64 before publishing the exact tested images.
