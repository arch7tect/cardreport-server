# Changelog

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
