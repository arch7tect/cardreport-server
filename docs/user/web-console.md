# Web console

[README](../../README.md) · [HTTP API](api.md)

Open `/ui/` on the API address: `http://127.0.0.1:18000/ui/` with Compose,
or `http://127.0.0.1:8000/ui/` for a native API. The console is served by the same
image/package, without Node, a frontend server or internet assets. Swagger remains
at `/docs`. JavaScript must be enabled. All internal callers share this workspace;
there is no per-user access control or private report history.

## Templates

Browse active/archived templates, open metadata and choose an immutable version.
Load more exposes additional templates and versions. Create a template by importing
JSON/YAML or pasting source and choosing its format. Save validates the source and
creates a version; an error retains the editor contents. The safe API error may
include a template path, not the full library traceback.

Create new version starts from the selected canonical JSON. Existing versions are
never overwritten. YAML comments/style are not stored. Copy/download exports that
canonical JSON. Another caller may save first, so the resulting version is the one
returned by the server, not necessarily the selected number plus one.

Archive blocks new versions and reports, while retaining existing definitions and
already accepted jobs. Restore enables new work. Concurrent changes are resolved
by the server. Unsaved source stays only in page memory; navigation warns before
discarding it. A reload or closed tab does not provide durable draft storage.

Service status checks API liveness and database/storage readiness on demand. It
does not assert worker health. OpenAPI, Swagger and raw metrics have direct links.

## Generate a report

Choose **New report**, select an active template and a version. Use Load more for
additional templates/versions. An explicit version is selected by default; Latest
at submission lets the server resolve the latest version before reading data.
A New report action on a template detail pins the viewed version.

Choose Chromium or WeasyPrint and PDF or HTML. WeasyPrint supports dashboard
layouts; use Chromium for flow and table pagination. Upload a JSON/YAML
`cardreport.data/1` bundle or paste its text. The extension suggests a media type;
you can change it explicitly. Files are submitted directly, without parsing their
contents in the browser.

Alternatively, choose **CSV files** and select multiple files in one selection.
Each filename supplies the dataset name (`summary.csv` → `summary`); column types
come from the pinned template. You may add one JSON/YAML bundle for other datasets.
Names must be unique across every input. Rename a local file to change its dataset
name. The console does not modify or persist the original files.

Expand **CSV options** to set encoding (default `utf-8`), a one-character delimiter
(default comma; enter `\t` for a tab), or exact null tokens, one per line. **Treat empty cells as null**
adds the empty token explicitly. Without that option, empty text stays empty and
empty numeric cells fail validation. Use `utf-8-sig` for UTF-8 CSV with a BOM.
Options apply to every CSV file in the submission; the optional bundle retains its
own JSON/YAML types. The full multipart body, including boundaries and options,
must fit the configured input cap. File-size prechecks cannot include all transport
overhead; the server remains authoritative.
The console checks library hard caps; configured server limits can be lower.

Generate submits once and opens the accepted job. A 202 response means that data
and job metadata were stored, not that parsing or rendering succeeded. The worker
performs those checks. If acceptance is uncertain after a lost response, check
Reports before deliberately resubmitting: the original job may already exist.
The same rule applies to saving a new template version. No mutation is retried
automatically; disabled buttons prevent accidental duplicate clicks while sending.
A closed or navigated-away page does not cancel server work.

## History, status and results

Reports lists retained jobs from every caller, with template ID and state filters.
Refresh starts at the newest page; Load more continues without reordering the rows
you are reading. The list is a live view, so concurrent commits/state changes and
retention are not a frozen snapshot. Expired rows retain the former terminal state,
including failed jobs. Once metadata retention ends, a report is no longer listed.

Open a row to see its bookmarkable UUID, pinned template, attempts, timestamps,
renderer/output, safe error and actual versions. Only the visible, nonterminal
detail is polled. Polling pauses in hidden tabs and stops on navigation or terminal
state; temporary read errors back off and mark the displayed status stale. Refresh
status is always available. Health/readiness and report success are separate checks.

Download retrieves the original committed bytes. **Open PDF** opens the same result
in a new tab using the browser’s native PDF viewer; Download remains a separate
action. Browser preferences or a missing PDF viewer may cause a download instead.
**Open HTML** opens the report in a separate tab at its original size, without
opening the embedded preview. It retains the server’s isolated HTML policy.
**Preview HTML** opens an isolated frame in the console; **Hide preview** closes
it and releases its resources. You can reopen it while the result is available.
If a result expires before Open HTML or Open PDF loads, the new tab displays
the API error.

Chromium and WeasyPrint HTML both work, but only PDF performs the authoritative
layout/export checks. **Fit width** scales the complete report to the available
width without rearranging its charts or tables; **100%** uses the original scale
with scrolling. The fit follows window resizing. If template dimensions cannot be
loaded, the preview remains available at its original scale. If retention expires after the status check, the frame may show
a safe JSON error; use Refresh status. The endpoint remains the final authority
on whether a result is downloadable. Failed/pending results have no partial output.

Use these settings prefills a new submission form; you must select or paste data
again. Stored inputs cannot be read through the API. There is no cancellation or
server-side rerun action. Drafts/data are never stored in browser localStorage or
sessionStorage, and the console does not add authentication or per-user visibility.

## API coverage

| API capability | Console location |
| --- | --- |
| List/filter templates and list versions | Templates, version selector, Load more |
| Get template/version definition | Template detail; canonical JSON copy/download |
| Create immutable version | Create template / Create new version |
| Archive and restore | Template detail |
| Submit report with data/renderer/output/version | New report |
| List retained jobs and filter | Reports |
| Get status/attempts/error/versions | Report detail |
| Get result content | Download; collapsible HTML preview with scaling; Open HTML/PDF in a new tab |
| Liveness and readiness | Service status |
| Swagger, OpenAPI, raw metrics | Navigation/footer links |

## Screenshots and tested scope

The screenshots use the bundled synthetic reference example.

![Template version in the console](../images/web-console-template.png)

![Completed report and isolated HTML preview](../images/web-console-report.png)

Browser acceptance uses Playwright Chromium. Desktop and narrow layouts are
checked; other browser engines are not yet verified. Deploy the console at the
root-hosted `/ui/` path alongside `/v1`, `/docs` and `/static`. Reverse-proxy
subpath rewriting is not supported. The UI and Swagger require no external assets.
