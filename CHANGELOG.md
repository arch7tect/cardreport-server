# Changelog

## 0.4.1

- Coordinate retention and orphan cleanup across workers with a PostgreSQL advisory
  lock, while keeping expired-lease recovery independent. Busy workers skip cleanup
  without waiting; failures close the dedicated lock connection.
- Document connection budgeting, session-pooling requirements and network-loss
  recovery. Retention durations and existing expiry timestamps are unchanged.

No database migration is required. Replace all workers to enable coordination;
older workers do not honor the cleanup lock.

## 0.4.0

- Search templates by ID or the latest report title, with case-insensitive literal
  substring matching. Show the latest title in the template list.
- Filter report history by creation date and time, with timezone-aware boundaries.
- Browse templates and reports in pages of 50 with Previous / Next, preserving
  filters and the current page when a page request fails.
- Enter retention in fractional days, show readable durations, and align retention
  controls with the save button. The API continues to use seconds.
- Preserve form focus when background page loading finishes, so typing and clearing
  retention settings are not interrupted.

No database migration is required when upgrading from 0.3.0.

## 0.3.0

- Preserve original input files for inspection and exact download, including failed
  reports. Show per-file parse results and dataset names in the web console.
- Download an investigation ZIP with original files, the raw request, pinned template,
  submitted CSV options, safe error and recorded execution versions.
- Configure retention per template, with a server default. New jobs snapshot one
  lifetime for originals, normalized data and output; existing jobs are unchanged.
- Add input download grace, bounded file viewers and API/Python replay documentation.

Upgrade requires coordinated API/worker replacement and migration 0008. Remove
`CARDREPORT_INPUT_RETENTION`; `CARDREPORT_RESULT_RETENTION` is now the shared default
(24 hours). Old uploads remain downloadable only while still retained; old reports
have no parse diagnostics. Templates and versions do not expire.

## 0.2.0

- Generate reports from multiple JSON, YAML and CSV files in one submission.
  Dataset names are merged without silent overrides; CSV types come from the template.
- Add files incrementally in the web console, remove individual files, and retain
  the selection when cancelling the file chooser. Configure CSV encoding, delimiter
  and null tokens when needed.
- Inspect the immutable datasets used for a successful report, browse rows in the
  console, and download the typed JSON snapshot. Data expires with the result.
- Add reference CSV fixtures, Python/curl examples, OpenAPI inputs and data endpoints.

Upgrade requires coordinated API/worker replacement and migration 0007. Existing
reports remain readable but have no saved dataset snapshot.

## 0.1.0

First release of CardReport Server, an internal HTTP service and web console for
CardReport. Ships as a Linux container for amd64 and arm64 with both renderers.

- Immutable JSON/YAML template versions, separate from streamed named datasets.
- Asynchronous PDF/HTML generation using Chromium or WeasyPrint.
- PostgreSQL queue with bounded concurrency, leases, retries and worker recovery.
- S3-compatible input/result storage, configurable retention and resource budgets.
- Web console for templates, submissions, retained history and downloads.
- HTML preview with Fit width / 100%, a close action, and separate-tab HTML/PDF viewing.
- FastAPI/OpenAPI, health checks, metrics, Compose and Kubernetes deployment guides.
- Tested image publication to GHCR and versioned GitHub releases.

There is no built-in authentication; use a trusted internal network. Chromium
supports dashboard and flow reports; WeasyPrint supports dashboard reports.
Production database/storage availability and access control remain operator duties.
