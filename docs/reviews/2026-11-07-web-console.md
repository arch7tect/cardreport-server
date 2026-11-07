# Web console design and plan review

Date: 2026-11-07. Scope: [design](../ui-design.md) and
[implementation plan](../ui-implementation-plan.md), not implementation approval
or deployment certification. Source baseline: `ee947ce`.

## Outcome

Two bounded read-only Claude consultations completed with exit 0. The first
approved the approach with changes; the focused follow-up found the revised plan
ready to implement, with no remaining material findings or overengineering.

| Finding | Disposition |
| --- | --- |
| Browser tests needed before their harness existed | Move harness option, direct Playwright dependency, local fixtures and CI browser installation to U2 |
| Existing sandbox headers may prevent native PDF viewing | PDF download only in v1; HTML inline preview is explicit, PDF inline returns 422 after availability checks |
| Sandbox/CSP described as a complete network boundary | Document self-navigation risk; test parent/fetch/resource protections separately from navigation; accept only library-generated HTML |
| Cursor/filter and expired-state ambiguity | Specify invalid_cursor, position-only cursor, live-view limitations and retained terminal_state |
| UI CSP could affect Swagger or be bypassed through another shell path | Scope headers to /ui/, keep assets outside Swagger static tree |
| Expiry race inside isolated preview | Document possible safe JSON response and provide status refresh; no new preview protocol |

The design preserves native JavaScript modules, no build step or new service,
textarea editing and existing library validation. History indexes use the existing
explicit migration and exact-revision upgrade policy. No authentication, visual
designer, saved datasets, stored-input rerun or worker redesign is added.

## Evidence and limits

- Inspected current template/report routes, jobs, streaming download handling,
  schema/migrations, package/container delivery and isolated Compose/pytest runner.
- Initial reviewer read both documents and the relevant routes, persistence,
  downloads, migration, packaging and harness code; follow-up reread both documents,
  previous findings and relevant download checks. It was advisory and read-only.
- Documentation checker validates local links, bundled template/data examples and
  deployment YAML; `git diff --check` validates whitespace.
- A temporary loopback prototype generated the bundled reference HTML through the
  installed public CardReport API and embedded it in Playwright Chromium using the
  exact proposed HTTP CSP and `sandbox="allow-scripts"`. It produced nine main SVGs
  and nine bar paths with no JavaScript errors. Source is retained under ignored
  `local/ui-preview-probe.py`; this was a disposable compatibility experiment.
- That prototype does not prove isolation, WeasyPrint preview, multi-browser
  support or the proposed interface. U4 still requires those relevant browser
  checks, including an explicit remaining self-navigation-risk test.
- No application implementation, schema migration, deployment or release occurred.
  Implementation tests and user documentation are acceptance work in each slice.
