# HTTP API

[README](../../README.md) · [Local development](local-development.md)

All resource paths start with `/v1`. `/docs` uses bundled Swagger UI assets and
`/openapi.json` describes the implemented API. There is no built-in authentication;
allow access only from trusted callers. All permitted callers can mutate templates.

## Templates

| Method/path | Result |
| --- | --- |
| POST /v1/templates/{id}/versions | Validate and create the next immutable version; 201 |
| GET /v1/templates | Metadata list; `archived`, `after` ID and `limit` (1–100) |
| GET /v1/templates/{id} | Metadata and latest version |
| GET /v1/templates/{id}/versions | Version metadata; `after` version and `limit` |
| GET /v1/templates/{id}/versions/{version} | Metadata plus canonical `definition` |
| PATCH /v1/templates/{id} | `{"archived": true}` or false |

IDs match `[a-z0-9][a-z0-9_-]{0,63}`. The POST body is an existing
`cardreport.template/1` envelope, with `Content-Type: application/json` or
`application/yaml`; UTF-8 only. Limit: 1 MiB. YAML comments/style are not stored.
The response includes the version, SHA-256 digest, library version and creation time.
The digest covers CardReport's compact JSON serialization, including mapping order;
semantically equivalent templates with reordered keys can have different digests.

```sh
curl --fail-with-body -H 'Content-Type: application/json' \
  --data-binary @template.json \
  http://127.0.0.1:18000/v1/templates/monthly/versions
```

Supply your existing CardReport template file. Both formats use the library's
schema/validation, including typed bindings; the server does not define new cells
or template expressions. The generated OpenAPI adapts packaged schema references.

Versions are allocated transactionally and never overwritten. Archive blocks new
versions and future submissions; stored definitions remain readable. Production
clients should pin a version: another authorized caller can change latest.
Pagination returns `items` and `next` (null when exhausted).

## Errors and health

Errors use `{"error":{"code":"...","message":"..."}}`, optionally with known
location fields. Invalid request parameters/templates return 422; unknown resources
404; archived templates 409; oversized input 413; unsupported media/encoding 415;
paused admission/dependency outages 503. Library error text and input values are
not returned. Error messages are stable server messages rather than parsed traces.

`/health/live` confirms the API process; `/health/ready` checks the expected database
schema and configured storage bucket. Startup fails if those checks fail. No schema
migration runs implicitly. CORS is disabled by default.

## Reports

| Method/path | Result |
| --- | --- |
| POST /v1/reports?template_id=monthly&template_version=1&output=pdf | Stream a dataset bundle; 202 after object + job commit |
| GET /v1/reports/{uuid} | State, pinned template, attempts, timestamps, safe error and actual versions |
| GET /v1/reports/{uuid}/content | Stream the committed successful PDF or HTML |

`template_version` is optional (latest is resolved before reading data). `output`
is `pdf` (default) or `html`. The raw body is `cardreport.data/1` in JSON or YAML,
with the corresponding Content-Type. Content-Length is optional; chunked upload is
supported. Gzip and other Content-Encoding values are rejected. The input cap is
16 MiB, checked against both headers and actual streamed bytes. Dataset validity is
checked later by the worker; malformed data may receive 202 and then fail.

The 202 body contains `id`, `state`, `template_id`, `template_version`, `output`,
`status_url` and `content_url`; Location points to status. The UUID is not an access
control mechanism. Lost responses can leave an accepted job; no idempotency key or
submission retry is provided. Archive after admission does not invalidate that job.

States: `queued`, `running`, `succeeded`, `failed`, `expired`. Failed and expired
records retain `terminal_state` and safe error until metadata retention ends.
Infrastructure failures may move running back to queued, incrementing attempts.
Only succeeded and unexpired reports are downloadable. Pending/failed returns 409,
expired output 410, unknown/removed metadata 404. Download includes Content-Type,
Content-Length, SHA-256 ETag, attachment filename, no-store and security headers.
Partial outputs are never discoverable through this endpoint.

Upload concurrency/backlog limits return 429 and Retry-After; upload idle/total
deadlines return 408. Temporary dependency failures return 503. See
[operations](operations.md) for limits, terminal error codes, retries and retention.
