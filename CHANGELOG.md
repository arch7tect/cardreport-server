# Changelog

## 0.2.0

- Generate PDF/HTML from multiple CSV files through the existing report API and
  web console. Filenames identify datasets; stored templates supply column types.
- Combine CSV files with an optional JSON/YAML bundle. Configure encoding,
  delimiter and exact null tokens without converting data on the client.
- Keep bounded streamed uploads, asynchronous validation, both renderers and
  cumulative dataset limits. Reject incomplete multipart bodies and duplicate names.
- Add reference CSV fixtures, Python/curl examples and OpenAPI multipart inputs.

Upgrade API and workers together after pausing admission and draining work. Old
workers cannot process multipart jobs. No database migration is required.

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
