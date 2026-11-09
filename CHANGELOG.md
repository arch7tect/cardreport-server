# Changelog

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
