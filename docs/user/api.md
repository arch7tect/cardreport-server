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
Getting one version also returns `page_dimensions_mm: [width, height]`, derived
through CardReport’s public Page API, without changing the stored definition/digest.
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
| GET /v1/reports | Retained history; optional template_id/state, after cursor and limit (1–100, default 50) |
| GET /v1/reports/{uuid} | State, pinned template, attempts, timestamps, safe error and actual versions |
| GET /v1/reports/{uuid}/content | Stream the committed successful PDF or HTML |

`template_version` is optional (latest is resolved before reading data). `output`
is `pdf` (default) or `html`. `renderer` is `chromium` (default) or `weasyprint`.
The raw body is `cardreport.data/1` in JSON or YAML (or [CSV multipart](#csv-input)),
with the corresponding Content-Type. Content-Length is optional; chunked upload is
supported. Gzip and other Content-Encoding values are rejected. The input cap is
16 MiB, checked against both headers and actual streamed bytes. Dataset validity is
checked later by the worker; malformed data may receive 202 and then fail.

The 202 body contains `id`, `state`, `template_id`, `template_version`, `output`, `renderer`,
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

## Inline result viewing

`GET /v1/reports/{uuid}/content?disposition=inline` streams the same committed
HTML or PDF with an inline filename. Omit disposition (or
use `attachment`) for the existing download behavior. Unknown values return 422.
Unavailable results still return the existing 404/410/409. PDF uses exact
`application/pdf`, nosniff and a CSP with `frame-ancestors 'none'`, without the
HTML sandbox that would block native PDF viewers. Open it as a top-level tab;
browser preferences may still select download. No range support is advertised.

Both modes keep size/hash headers, no-store, expiry rechecks and bounded streaming.
HTML preview permits the embedded Plotly scripts but denies same-origin access,
fetch/XHR, external resource loads, forms and popups. A report can still navigate
itself: sandbox/CSP are not a total network boundary. Only library-generated HTML
from validated templates/data is supported, not arbitrary uploaded HTML/scripts.
See the [web console](web-console.md) for preview behavior and limitations.

## Report history

`GET /v1/reports` lists all callers' retained jobs, newest first by creation time
and UUID. Filter by `template_id` (including archived templates) and/or one `state`.
An unknown template filter returns an empty list. Items have the same public fields
as report status, without storage keys, input data or ownership tokens.

The response has `items` and `next` (null at the end). Pass `next` unchanged as
`after`; malformed cursors return 422 `invalid_cursor`. Cursors encode position,
not filters, and survive removal of the boundary row. Clear the cursor when
changing filters to start from the newest match. Pagination is a live view:
concurrent commits, state changes or retention are not a frozen snapshot. Refresh
the first page for new jobs. `expired` includes formerly failed and succeeded jobs;
`terminal_state` distinguishes them. History has no total count or input-read API.

## Renderer selection

Select an engine per submission, independently of the stored template and input
format: `POST /v1/reports?template_id=monthly&output=pdf&renderer=weasyprint`.
The selection is persisted, returned in acceptance/status responses and retained
across retries. Omitted `renderer` and jobs created before this option use Chromium.
Unknown names return 422 before upload. Both engines are installed in every worker;
there is no automatic fallback or per-renderer queue.

| Engine | PDF | HTML | Layout modes |
| --- | --- | --- | --- |
| `chromium` (default) | Playwright/Chromium | Self-contained preview; JavaScript required to draw charts | dashboard, flow |
| `weasyprint` | SVG/WeasyPrint; no browser | Self-contained SVG preview; no JavaScript | dashboard only |

PDF is the authoritative checked output. Chromium HTML does not run browser layout
checks during generation; WeasyPrint measures layout during export, but another
browser may lay out its HTML differently. WeasyPrint HTML has a fixed 30-second
library export timeout; increasing the server attempt budget cannot extend it.
A shorter attempt budget is still enforced by the supervisor. Both produce
noninteractive charts.
WeasyPrint has the library's experimental feature subset, including bars, lines and
funnels. Flow/table splitting is unsupported and ends the job with
`unsupported_feature` (`retryable=false`), including HTML requests. Template
registration validates syntax independently of renderer capabilities. With the
pinned library, a severely oversized dashboard table can produce `render_failed`
instead of `layout_overflow` on WeasyPrint. Use Chromium flow for table pagination.
See the
[CardReport capability matrix](https://github.com/arch7tect/cardreport/blob/main/docs/user/renderers.md#capabilities).


## CSV input

`POST /v1/reports` accepts `multipart/form-data` with **any combination of multiple
JSON, YAML and CSV files**. CSV is optional. Query parameters, admission, 202
semantics and retries are the same as raw JSON/YAML. Template registration remains
separate. A raw `text/csv` body is unsupported because a report may need several datasets.

| Part | Meaning |
| --- | --- |
| `files` (repeat, required, at most 32) | `.json`, `.yaml`, `.yml` bundles or `.csv` files |
| `csv_encoding` | Python text encoding; default `utf-8`; use `utf-8-sig` for BOM files |
| `csv_delimiter` | One character, default comma; CR, LF and NUL are rejected |
| `csv_null` (repeat, optional) | Exact tokens converted to null; none by default; at most 32 |

Each JSON/YAML file contains a standard `cardreport.data/1` bundle and supplies its
own dataset names. Its filename is only a label. CSV filenames name datasets:
`summary.csv` supplies `summary`, whose fields/types come from the pinned template.
CSV files include a header. No schema inference, pandas, SQL or external fetch is involved.

All datasets are merged; duplicate names are errors, never overrides. Names are
case-sensitive, file extensions case-insensitive. Use plain filenames without path
separators. Unknown CSV datasets, unsupported extensions and unknown/repeated
options fail validation. File types come from extensions, not part Content-Type.
Client filenames are never used as server filesystem paths.

Options apply to every CSV; JSON/YAML types are unaffected. Each text option is
limited to 1 KiB. Encoding/delimiter occur at most once. Empty strings are not null
unless an empty `csv_null` is supplied.

```sh
curl --fail-with-body \
  'http://127.0.0.1:18000/v1/reports?template_id=monthly&template_version=1&renderer=weasyprint' \
  -F 'files=@summary.csv' \
  -F 'files=@export.csv;filename=payments.csv' \
  -F 'files=@other.yaml' \
  -F 'files=@additional.json' \
  -F 'csv_encoding=utf-8-sig' \
  -F 'csv_delimiter=;' \
  -F 'csv_null=NULL' \
  -F 'csv_null='
```

`filename=payments.csv` provides an alias without renaming the local file. Let
curl, httpx or browser FormData construct the boundary. Swagger `/docs` exposes
one repeated file list and optional CSV settings. No separate `data` part is accepted.

The **entire request**, including framing/options, must fit `CARDREPORT_INPUT_LIMIT`
(at most 16 MiB). Combined dataset limits apply across files. The API streams and
hashes the raw upload; the child parses it with Starlette/python-multipart, uses
CardReport's public adapters and binds with configured limits. Temporary spools
are closed and generated scratch paths removed after use. This is bounded file
loading, not constant-memory row streaming.

A missing/invalid boundary returns 400, unsupported encoding/charset 415, oversized
upload 413. Invalid bodies are accepted as jobs (202), then fail terminally with
`invalid_data`, stage `bind`, without exposing cell contents in error messages.
Normalized data must also fit the fixed 16 MiB snapshot ceiling. CSV/YAML can expand
during canonical serialization; excessive expansion fails before rendering with
`data_snapshot_too_large`. Lowering the raw upload limit does not lower this ceiling.

## Report data

Every new successful report saves a lossless `cardreport.data/1` snapshot of the
combined typed inputs used for binding, including unused datasets. It is committed
atomically with the result pointers and cannot be replaced by a stale attempt.
This is normalized input, not the original files or rendered/aggregated chart values.
Dates, decimals and nulls retain their types; changing the template later does not
change the snapshot. Failed reports and older reports have no saved snapshot.

- `GET /v1/reports/{id}/data`: download canonical JSON, with length/hash headers.
- `GET /v1/reports/{id}/datasets`: `{ "items": [{ "name": "summary", "columns": ["total"], "row_count": 1 }] }`.
- `GET /v1/reports/{id}/dataset?name=summary&offset=0&limit=100`: a page containing
  `name`, `columns`, `row_count`, `offset` and `rows` (arrays of cells).

Paged cells are display strings, except null which remains JSON null. Integers and
decimals retain exact digits; dates/datetimes use ISO format including offsets,
booleans use `true`/`false`. Download `/data` for typed data instead of display strings.
`name` is an exact query value, including Unicode or slashes; it is not a storage path.
`offset` is nonnegative; `limit` is 1–100, default 100. Beyond the last row returns
an empty page. Dataset names/row counts let the console select and page without
loading every cell into browser memory.

Status/history include `data_available`. All data endpoints share result expiry:
409 for unfinished/failed reports, 410 after result expiry, 404 for a missing report,
`data_unavailable` for an older successful report, or `dataset_not_found` for an
unknown dataset. Successful views/downloads use `Cache-Control: no-store`. Each view reads a
bounded, size/hash-verified snapshot; per-API `CARDREPORT_DATA_VIEW_SLOTS` (default 2)
limits concurrent views. Busy views return 503 with Retry-After. Corrupt snapshots
return 503 `data_integrity`; a view exceeding its read budget returns 504 `data_timeout`. There is no cache,
search, data editing, failed-input viewer or automatic rerun.

Snapshots survive raw input collection and expire with the result. Coordinated
upgrade and migration are required; see [operations](operations.md#file-input-and-report-data-upgrade).
