# Original input files and template retention review

Date: 2026-11-09. Baseline: a6ee483. Target: 0.3.0.

## Scope and decisions

Files are logical, ordered views of the immutable accepted raw object. Preserve
bytes, original names, hashes, CSV options and per-file decoding results. Keep
normalized successful-report datasets as a separate representation. A shared
structural extractor serves the child and input download routes; no per-file S3
copies, database table, reusable upload registry or extra cleanup service.

Template metadata has one nullable retention override, resolved and captured before
upload. New jobs use equal input/result durations starting at terminal completion;
metadata lives beyond artifacts and download grace. Existing durations and expiry
remain untouched. Migration 0008 is additive; coordinated stop/migrate/start and
exact schema gates apply. Templates/versions are not removed by report retention.

## Claude consultations

Actual read-only Claude Code design, implementation and final follow-up reviews
completed with exit 0. The design supported virtual files and fenced parse results.
Confirmed implementation findings were addressed:

- Remove avoidable copies during ZIP construction; return a buffer view and retain
  the bounded viewer slot through response delivery. Document per-slot memory.
- Bound structural metadata expansion in catalogs/archives to 64 KiB; an invalid
  structure remains downloadable as raw bytes.
- Preserve parse results on post-render size failures. Invalid optional diagnostics
  are discarded safely instead of turning an otherwise successful report into a
  failure. No cell values are copied into error strings.
- Reject the retired input-retention setting with an actionable message even for
  non-integer/empty environment values. Name old jobs' displayed duration accurately
  as input retention.

The final reviewer found no release blockers, conditional on passing the complete
suite. We retained generated safe download/archive paths; original names are in
metadata. The archive always includes the exact request for replay. The retention
upper bound follows database integer capacity rather than an arbitrary one-year
product limit. Worker supervisors re-extract bounded multipart only to verify file
indices; CSV/YAML decoding stays isolated in the child.

## Verification

Tests exercise exact bytes and duplicate names, malformed and empty originals,
failed-job downloads, fenced diagnostics, advisory diagnostics validation, download
capacity/deadlines/expiry, deletion grace, admission-time policy capture and migration
preservation. Browser coverage includes template override/inheritance, failed CSV
inspection and ZIP/original download. Both Chromium and WeasyPrint exercise mixed
input parsing in real worker containers.

Two older browser assertions expected a single-file upload to use raw transport.
The console now always preserves filenames through multipart; those assertions now
verify the raw request hash and the individual file bytes/name independently.
Raw consultation output, isolated test logs and generated evidence remain ignored.

Final local candidate: 147 unit, 48 PostgreSQL/S3 integration, 26 container and
39 browser checks passed (260 cases). Ruff, formatting, strict mypy (70 files),
133 local documentation links/fixtures/deployment YAML and an installed-wheel
check outside the source checkout passed. The documented investigation ZIP and
exact-request replay example ran successfully against an isolated installation.


## Publication verification

Release [v0.3.0](https://github.com/arch7tect/cardreport-server/releases/tag/v0.3.0)
points to 4978415dd9e1b85f9172c53879544f73eb903899. The
[release pipeline](https://github.com/arch7tect/cardreport-server/actions/runs/42633853179)
passed all 260 cases on each native Linux architecture, amd64 and arm64.
The versioned GHCR tag and latest have the same multi-platform digest:
`sha256:a558ae427a9f55c00fda0c714a8b676290f09c47fc3e33a007fb8e5c917fa123`.

Anonymous pull and a fresh installation from that published digest passed explicit
migration, console readiness, mixed-input PDF/HTML generation on both renderers,
original-byte and archive checks, failed CSV inspection and retention capture.
The local development upgrade preserved all pre-existing template/report rows.
The published image and release asset agree on source commit and version. This
post-release documentation update clarifies that the file catalog depends on the
retained raw upload, while dataset names/parse results persist in report metadata.
