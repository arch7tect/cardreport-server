# Preview scaling, native PDF viewing and toolbar alignment

Date: 2026-11-07. Baseline: `b6b1397`. Owner requested fitting HTML to the
preview width, opening PDF in the browser, and aligning filter buttons with fields.

## Changes and boundaries

- Template-version reads expose `page_dimensions_mm` through CardReport's public
  Page API. Stored definitions and digests stay unchanged; no migration is needed.
- HTML uses a fixed natural-width iframe with Fit width / 100% controls. A bounded
  viewport and ResizeObserver change only the view. The opaque-origin sandbox,
  HTTP CSP, original bytes and streaming path remain unchanged. Metadata failures
  fall back to the original layout; preview replacement/navigation disposes observers.
- PDF has a separate Open PDF link with noopener/noreferrer. Inline PDF keeps the
  original bytes, expiry checks, nosniff, application/pdf and restrictive CSP,
  including frame-ancestors none, but no CSP sandbox. HTML and attachment policies
  are unchanged. No range support, PDF.js, conversion or new service is added.
- Toolbar controls use bottom alignment and a common minimum height, including
  narrow layouts. Template and report filters were visually checked in the console.

Browser preferences can still choose PDF downloading; expiry races can show the
safe API error in the new tab. Only library-generated PDF/HTML is supported.

## Review and verification

The bounded design consultation completed with exit 0. Accepted advice covered
metadata fallback, bounded iframe geometry, shared cleanup, unchanged streaming,
no range advertisement and PDF expiry explanation. Speculative filtering of future
Page fields was not added: current stored versions are validated by the pinned
library's schema, and dimensions use its public API.

The initial advisory said native PDF viewing could not be tested headlessly. That
claim is outdated for full Chromium's new headless mode. The
[Playwright browser guide](https://playwright.dev/docs/browsers#chromium-new-headless-mode)
and [upstream change notice](https://github.com/microsoft/playwright/issues/33566)
distinguish it from headless-shell. Viewer checks launch `channel="chromium"` and
verify the real extension's page selector, no download event and no opener; actual
rendered PDF pages were also inspected in a screenshot. Both engine PDFs pass.
Other browser engines are not claimed as verified.

[MDN Content-Disposition](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Disposition)
and [iframe viewer guidance](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/iframe)
explain inline delivery and why HTML sandbox restrictions can block a native viewer.
The selected PDF CSP was exercised in full Chromium; HTML isolation tests remain
part of the browser suite.

The final bounded consultation also completed with exit 0 and no blockers. It
confirmed geometry, observer cleanup, fallback, response contracts and the native
viewer checks. Optional future compatibility layers and additional viewer engines
remain outside this focused change.

Final local acceptance passed 135 tests: 41 unit, 39 PostgreSQL/S3 integration,
22 container and 33 browser cases. Ruff/format, strict mypy (56 files), local
documentation links/examples/deployment YAML and diff whitespace checks passed.
The full integration/container/browser run used a fresh isolated Compose stack
and removed only its own resources on success. The normal local API was updated
and visually checked without changing stored templates or reports. No schema
migration, package release or production deployment was needed.
