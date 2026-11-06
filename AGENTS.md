# CardReport Server contributor instructions

Use Python 3.12+ and uv. Write repository code and documentation in English.
Read docs/design.md and docs/implementation-plan.md before implementation. The initial implementation is available;
README and the verification record describe tested behavior and remaining limits.

Keep template management separate from report submission and dataset transport.
Depend on CardReport's public API and packaged formats; do not copy its renderers,
validators or JSON Schemas. Keep server orchestration out of the library.

Prefer concrete modules and bounded concurrency to plugin frameworks. Jobs must
survive worker replacement. A pod is not limited to one concurrent report.
No authentication, SQL execution, visual editor, scheduler or external asset
fetching is in the first version. Internal network access is an operator contract.

Before studying or changing existing code, fetch refs and fast-forward only when
safe. Preserve unrelated changes. Add meaningful tests alongside implementation.
Keep README, API documentation and examples aligned with implemented slices.
Do not create a remote, deploy, publish packages or release without authorization.
Keep .venv, .idea, local configuration, raw reviews and generated reports ignored.
