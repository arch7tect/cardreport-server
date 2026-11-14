# Timezone hotfix integration

The owner authorized Server 0.5.1 with CardReport 0.9.1 and a local Compose upgrade.
The server continues to delegate template validation, binding and rendering to
the library. There is no timezone submission parameter, runtime interpreter, UI
setting or database migration. Presentation belongs to each immutable template.

Restricted cross-repository Claude review completed successfully. The public
library release must precede lock refresh, tests, image builds and server release;
no local-path dependency or private wheel enters the released image.

The daily JSON/YAML/CSV fixtures now combine a calendar date with a timestamp.
`report.timezone: Asia/Nicosia` displays 22:30Z as 00:30 the next day, while the
calendar date remains unchanged. Container tests assert this through both PDF
engines and HTML. The console test uses an America/Los_Angeles browser timezone,
checks the localized text and verifies byte-identical original CSV download.
Registration tests preserve the zone and expression source and locate invalid-zone
errors at `report.timezone`. The packaged data schema automatically updates OpenAPI.

Existing immutable template versions are not rewritten. Operators can append a
version selecting UTC if they need the previous display policy. Normalized naive
inputs now carry +00:00; original uploads remain unchanged. Follow the standard
coordinated API/worker upgrade, retaining the previous image and database backup.

Final local checks used the public PyPI 0.9.1 package and its exact lock hashes:
161 unit, 56 PostgreSQL/S3 integration, 31 container and 51 browser tests passed
(299 total). Ruff/format (123 files), strict mypy (75 files), 158 documentation links
plus fixtures/deployment YAML and installed-wheel console/Swagger checks passed.
The isolated harness removed only its own successful test stack. Original local
Compose remains separate until the published-image rollout.
