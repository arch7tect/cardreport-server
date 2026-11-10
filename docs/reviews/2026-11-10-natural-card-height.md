# Natural card height dependency update

The library owns layout and rendering. Server 0.4.3 requires CardReport 0.8.4
and locks the published package; no server renderer workaround or migration is
introduced. Both API and workers use the same tested image.

CardReport fixes WeasyPrint auto-height cards by distinguishing natural sizing
from definite-height grid allocation. Standalone table cards can grow with their
contents; fixed-height layouts retain overflow checks. The library covers nested,
weighted and unweighted containers, mixed contents and genuine overflow.

The restricted Claude review found no implementation blocker. It required the
published dependency/lock update before release and confirmation that the new
server regression fails on the old engine. That exact synthetic nine-row table
case failed with LayoutOverflowError at blocks.1 in the published 0.4.2 image
(CardReport 0.8.3), without accessing a database or changing the developer stack.
The server test submits the same layout through the API, waits for the worker,
and checks a complete one-page PDF with every table row and the following block,
for both Chromium and WeasyPrint.

User documentation describes natural heights and their limits: no dashboard card
pagination, no automatic expansion of explicitly fixed rows, and no suppression
of real overflow. Old outputs and immutable template versions remain unchanged;
previously failed reports must be submitted again after the coordinated upgrade.

The final restricted Claude review confirmed the official dependency lock and
regression coverage. The first container run passed 27 cases; its only failure
was an old expectation that a severely oversized natural table caused a generic
render failure. The corrected engine now raises layout_overflow with a validated
diagnostic. The test and API/changelog descriptions were updated accordingly,
without weakening detection. A stale minimum-version claim in the operations
guide was replaced with a link to the authoritative dependency declaration.

Final local acceptance with the official PyPI wheel passed: Ruff/formatting,
strict mypy, 157 unit tests, 55 PostgreSQL/S3 integration tests, all 28 container
cases and 48 browser cases (288 total). Documentation checks covered 144 local
links, bundled examples and deployment YAML. The installed-wheel console and
Swagger check passed outside the checkout. Publication still requires both native
Linux architecture CI lanes and verification of the released image.
