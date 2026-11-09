# Web console design

Status: implemented; design and implementation reviewed with Claude.
Owner: Oleg Orlov. Date: 2026-11-07.

This adds a small developer-facing console to the existing service. The
[implementation plan](ui-implementation-plan.md) records delivery slices. See the
[design review](reviews/2026-11-07-web-console.md),
[implementation verification](reviews/2026-11-07-web-console-implementation.md) and
[user guide](user/web-console.md).
The [architecture](architecture.md) describes current runtime behavior;
[HTTP API](user/api.md) remains the current API reference.

The 0.2 [CSV input extension](user/api.md#csv-input) supersedes the CSV exclusion
in this original design; other boundaries remain unchanged.

## Scope and choices

The console covers template management, report submission, history, status and
results through the public HTTP API. It lives at `/ui/` in this repository and is
served by FastAPI in the existing image. PostgreSQL and S3 remain the only durable
stores; workers and rendering are unchanged. No separate frontend service, BFF,
WebSocket, broker, client database or generated SDK.

Use browser-native JavaScript modules, HTML and CSS, without a build step or Node
runtime. Three small screens do not justify a component framework or bundler yet.
Keep API calls, navigation and screen code in separate modules; do not build a
custom UI framework. Use a plain labelled textarea for template source in v1.
The console's interface and documentation are English; report languages remain
properties of the template. Use the user's browser locale for displayed timestamps
and include the time zone, without modifying template/data values.

Out of scope: visual report designer, syntax-completion editor, version diff,
CSV conversion, saved datasets, SQL connectors, scheduling, cancellation, manual
retry of stored input, deletion of templates/reports, authentication/roles,
operational settings mutations and full monitoring dashboards. These features
are not part of the current API either. Swagger stays at `/docs`.

Two additive API changes are required: a report list and an inline content option.
No second interpretation of CardReport JSON/YAML or copied validation schemas.

## Screens and API coverage

Navigation: **Templates**, **New report**, **Reports**, plus links to **API docs**
and **Service status**. Status is a small panel, not another dashboard. All users
of the internal service see the same templates and retained report history.

| API operation | Console action |
| --- | --- |
| GET templates, with archive filter and pagination | Browse active, archived or all templates |
| GET template metadata | Template detail with ID, state and latest version |
| GET template versions and a specific version | Paginated version selector, metadata and canonical definition |
| POST template version | Create a template or save edited/imported source as a new immutable version |
| PATCH template archived flag | Archive or restore, with an explanation before archiving |
| POST report | Choose a stored version, data, renderer and output; submit once |
| GET reports (new) | Shared, paginated report history with template/state filters |
| GET report by UUID | Bookmarkable detail, state, timestamps, attempts, versions and safe error |
| GET report content | Preview when supported; download the original bytes |
| GET health/live and health/ready | Explicit status refresh with check time, without claiming worker health |
| GET metrics | Link to the existing metrics endpoint; no duplicate charts |
| GET docs and openapi.json | Links to Swagger and the API schema |

### Templates

A list has archive filter, Load more and Create template. Detail shows version
metadata, canonical JSON and actions: New version, New report, Archive/Restore.
Older versions stay viewable. Archived templates cannot create versions or reports;
the server still decides if a concurrent archive invalidates an action.

Creation accepts a slug plus either a JSON/YAML file or pasted source, with an
explicit format selector. Importing a template file into the textarea is allowed
because template size is bounded. Server validation is authoritative; show its
safe error code/message and template path without guessing missing diagnostics.
Do not claim a separate validation step: validation and version creation are the
same existing operation. Invalid source creates no version.

Editing starts from the selected canonical JSON and saves a new version. Never
label this as overwriting the selected version. YAML source can be submitted,
but comments/style are not preserved by storage. A concurrent writer may create a
version first; display the actual version returned by the server. Do not assume
selected version + 1. Offer download/copy of canonical JSON, not original YAML.

Keep unsaved text while the user stays in the console; confirm internal navigation
that would discard it and register a browser unload warning where supported.
Do not persist templates or dataset contents in localStorage/sessionStorage.

### New report

Select an active template and a specific stored version by default. Also expose
an explicit Latest at submission choice, explaining when it is resolved. A link
from a version detail pins that version. Lists/version selectors are paginated;
templates beyond the first page must remain selectable.

Accept a JSON/YAML dataset bundle as a file or pasted text. Infer the format from
`.json`, `.yaml` or `.yml`, but allow explicit selection; do not trust File.type.
Send a selected File directly as the request body with the chosen Content-Type.
Do not call file.text(), JSON.parse or a YAML parser on a dataset file just to
submit it. Pasted text is sent as UTF-8. This avoids an unnecessary decoded copy;
it does not promise zero-copy transport or streaming rendering. No CSV controls.

Renderer: Chromium/WeasyPrint. Output: PDF/HTML. Explain the WeasyPrint dashboard
restriction and HTML preview semantics, without implementing a duplicate capability
validator. Do not create another template as part of submission.

Disable the submit button while sending. Show Sending, then Accepted with the UUID
and pinned version, then the real job status. HTTP 202 is not render success.
Do not invent upload percentages or completion estimates. Never auto-retry a
report or template-version POST. A network/timeout/server error can leave a durable
job/version; keep the draft, explain uncertain acceptance and link to history or
versions before a deliberate resubmission. Finding a similar row is not proof of
which request succeeded. Leaving the screen does not cancel an admitted job.

### Reports and detail

List newest first, with template ID and state filters, refresh and Load more.
Rows show ID, template/version, renderer/output, state and creation time. No total
count is needed. Changing filters or pressing Refresh starts a new first page.
Do not automatically reorder a history list while someone is selecting a row.

Detail includes attempts, start/finish/expiry timestamps, terminal state, safe
error and actual service/engine/image versions. Copy ID/link and open the pinned
template version. An optional Use these settings action only prefills template,
version, renderer and output; users must supply data again. There is no input-read
API or server-side resubmit operation.

Poll only the visible nonterminal report detail: start at two seconds, one request
at a time, pause while the tab is hidden, resume when visible. Stop on terminal
state, 404 or navigation. Back off transient GET failures up to 30 seconds and honor
Retry-After; offer manual refresh. Requeued jobs can legitimately go from running
back to queued. Show stale status explicitly after a failed fetch. A succeeded job
can expire later: recheck on detail entry/focus and before preview/download; the
content endpoint is the final authority for 409/410/404.

Hash routes such as `/ui/#/reports/<uuid>` make bookmarks and refresh work with one
static index page. No catch-all route may intercept `/v1`, `/docs` or unknown API
paths. A root-path reverse-proxy deployment is the supported initial configuration,
matching current absolute API URLs; arbitrary subpath hosting is not added here.

## Report history API

Add `GET /v1/reports` with:

- `template_id`: optional slug, same format as submission; unknown ID returns an
  empty list, not an error. Archived templates are valid filters.
- `state`: optional single value from queued/running/succeeded/failed/expired.
- `limit`: 1–100, default 50.
- `after`: optional bounded opaque cursor (at most 512 characters).

Return `{"items": [...], "next": "..."}`; next is null on exhaustion. Each item
uses the existing status projection, including safe error and version fields.
Reuse that small SQL projection rather than SELECT * or a second unrelated DTO.
Never expose input/result storage keys, ownership tokens, raw input or credentials.

Order by `(created_at DESC, id DESC)`. Fetch limit + 1; next encodes the last
returned row's exact database timestamp and UUID. Use a versioned URL-safe base64
JSON tuple, with bounded decode, timezone-aware timestamp and UUID validation;
malformed/unsupported cursors return `APIError(422, "invalid_cursor", ...)`
with a safe message. Preserve microsecond precision
server-side; the browser treats the cursor as opaque. The cursor carries position,
not filters: changing filters while reusing it applies the new filter below the
same boundary. The UI always clears it on filter changes. Cursors are not credentials
and do not need signing. Continuation compares tuple values, not a lookup of the
cursor row, so metadata deletion does not invalidate the position.

Pagination is a live view, not a database snapshot. New rows normally appear on a
first-page refresh; state changes can move rows into/out of filtered results.
Avoid duplicates within a traversal using the strict tuple boundary. Do not
promise a complete snapshot under concurrent insert/retention/state changes; a
transaction committed late can appear behind an already traversed boundary.
The expired filter includes both formerly succeeded and formerly failed jobs;
show terminal_state alongside expired in list and detail.

Add indexes for `(created_at DESC, id DESC)` and
`(template_id, created_at DESC, id DESC)` in one additive migration. State filters
use the same query initially; add more indexes only on measured need. Query values
are bound parameters, with no user-supplied SQL order/column expressions. Update
the exact expected schema revision and apply the existing coordinated upgrade
procedure. An old image may refuse the new revision even though data is preserved;
rollback requires a compatible image or forward fix, not a destructive downgrade.

## Result preview and browser boundaries

Keep `GET /v1/reports/{id}/content` and its default attachment behavior. Add
`disposition=attachment|inline`, default attachment; reject other values with 422.
Inline supports HTML and PDF after the existing 404/410/409 availability checks.
Normal downloads are unchanged. Both modes share the existing ownership-independent result lookup,
expiry recheck,
streaming, timeout and body closure. Do not generate a second artifact or buffer
an entire report in the API/browser just to preview it.

HTML inline mode sets the correct Content-Type and inline filename, no-store and
nosniff. Its HTTP CSP permits scripts only for the report itself, using
`sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline';
style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none';
base-uri 'none'; form-action 'none'; frame-ancestors 'self'`.
The UI embeds its URL in an iframe with `sandbox="allow-scripts"`, never
allow-same-origin, forms, popups, downloads or top navigation. Chromium HTML needs
its inline Plotly scripts; WeasyPrint HTML works without scripts. Verify real
outputs under this policy before committing to it; do not silently relax network
or origin isolation to make a chart render. Existing attachment CSP is unchanged.

The console defaults to Fit width: obtain `page_dimensions_mm` from the pinned
version metadata, computed with CardReport’s public Page API, and scale an iframe
at that natural width inside a bounded viewport. ResizeObserver follows the
viewport; 100% restores original size with scrolling. Dispose the observer when
replacing/hiding the preview or leaving the page. Preview HTML toggles to Hide
preview; closing removes the iframe and reopening starts at Fit width. Open HTML
uses the same inline endpoint in a new tab with noopener/noreferrer, retaining
the response CSP sandbox even outside the embedded frame. Metadata failure falls back to
an unscaled frame. Never access the isolated report DOM or rewrite its content.

PDF has separate Download and Open PDF actions. Open PDF is a direct new-tab link
with noopener/noreferrer; the browser’s native viewer handles the document. The
PDF inline response keeps application/pdf, nosniff, no-store and the CSP
`default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`.
It omits CSP sandbox, which prevents the native viewer from loading.
The response still streams the same bytes through the existing expiry/timeout
checks; no range support is advertised. A retention race can show a safe JSON
error in the new tab. Browser preferences may choose downloading instead.
No PDF.js, page rasterization or embedding of PDF in the console is introduced.
This extends the initial PDF-download-only design at the owner’s request.

Never insert report HTML, template source or error text into the console DOM as
HTML. Use textContent/form values for text. Sandbox prevents report scripts from
reading the
parent DOM/storage; CSP blocks fetch/XHR and resource loads beyond the permitted
inline/data assets. This is not a complete network boundary: a frame or a directly
opened preview can navigate itself to another URL, potentially including data in
the URL. No supported CSP navigation directive closes that gap. Parent/top
navigation and popups remain blocked in the embedded preview. Tests must verify
these distinctions rather than assert that every possible request is prevented.

Only CardReport-generated HTML from validated templates/data is served. The service
does not accept arbitrary HTML/JavaScript; rendering escapes user text and supplies
its own chart/layout scripts. Treat that output contract as part of the trusted
renderer dependency and test markup-like template/data strings at the UI boundary.
Supporting hostile HTML would require a different isolation design, outside v1.
The UI shell has a separate restrictive CSP with same-origin modules/styles/API
and frames; it does not need unsafe-inline scripts. Keep script-dependent reports
outside that shell document and do not copy HTML into a same-origin blob preview.
Scope the shell CSP to `/ui/` only; Swagger uses inline initialization and must
retain its own behavior. A race after the pre-preview status check can display
a safe 409/410/404 JSON error in the isolated frame. The parent cannot read it; keep
a visible Refresh status action and explain this case rather than adding another
preview transport protocol.

There is no authentication change. Showing all retained report metadata is an
intentional extension for trusted internal callers. This is not a hostile-tenant
sandbox or an administrative access boundary. UI service status is API readiness,
not proof that workers are healthy or a report will succeed.

## Packaging, interaction and failure handling

Store the shell and assets under `src/cardreport_server/web/`; mount `/ui/`
with index handling and serve JavaScript with the correct MIME type. Use the
existing package/static delivery approach, ensuring wheel and container inclusion.
Keep these files outside the existing Swagger `/static` tree so the shell cannot
be reached through an alternate route without its UI-specific headers.
No CDN/fonts/analytics requests, build-generated assets or Node installation.
Use cache revalidation/no-cache for shell and unhashed assets to avoid stale module
combinations after an upgrade. StaticFiles needs a small response hook/subclass
for that Cache-Control header; ETag alone is insufficient. `/ui` redirects to
`/ui/`; missing assets are 404.

Use one small API helper for JSON responses and structured errors, and plain
modules for templates, submission and reports. Use AbortController/request tokens
for stale GETs and view disposal, with bounded GET timeouts; never use a generic
retry wrapper for mutations. A POST network abort does not undo server work.
Download links go directly to the endpoint. Loading/empty/error states retain
useful context and never replace a populated editor on a background refresh.

Use semantic forms/tables, visible labels, keyboard navigation, focus after dialogs
and errors, and text alongside colored status badges. Tables may scroll on narrow
screens; forms stack. Test a desktop and a narrow viewport. Do not add a design
system package for these screens.

The server remains authoritative for configured limits. The console can prevent
obviously impossible files above the library hard limits, but must not claim those
are the deployment's actual settings; display server rejections. No new config or
schema endpoint solely for frontend hints in v1.

## Verification and completion

API integration tests cover list filtering, cursor precision, deletion/concurrent
changes, safe field projection, migration and default/inline content compatibility.
Browser tests cover each user workflow, real JSON/YAML submission, terminal errors,
uncertain responses without duplicate POSTs, draft retention and pagination.
Security tests exercise an isolated synthetic HTML result with attempted parent/API
access, plus actual Chromium/WeasyPrint chart previews with no external network.
Fixtures must never create a production test endpoint or modify developer data.

Use pytest with Python Playwright sync_api, local fixtures and Chromium, extending the existing isolated
Compose harness. A small mocked-response browser lane covers transient/edge states;
real API/DB/S3/workers must prove the main workflow and preview. Do not claim broader
browser support from Chromium alone. Capture synthetic screenshots for the guide
and failure traces under ignored local paths. Tests, documentation, packaging and
CI are required delivery work, specified in the plan.

## Sources

- Current [API reference](user/api.md), [template routes](../src/cardreport_server/templates.py),
  [report routes](../src/cardreport_server/reports.py), [jobs](../src/cardreport_server/jobs.py)
  and [download handling](../src/cardreport_server/downloads.py).
- [MDN iframe sandbox](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/iframe)
  and [HTTP CSP sandbox](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/sandbox)
  for preview isolation; these describe platform behavior, not verification of our outputs.
- [Playwright Python pytest support](https://playwright.dev/python/docs/test-runners)
  for the browser-test lane.
