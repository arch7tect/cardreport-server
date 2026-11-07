# Architecture documentation review

Scope: implemented architecture and worker lifecycle, high availability, scaling
and navigation from README, design and user guides. Runtime baseline: `e28470d`.
No runtime, dependency, deployment-manifest or package-version changes.

## Review and dispositions

The initial Claude review found no blockers and identified three accuracy issues:
server-side database timeouts do not bound a lost client connection; recovery error
codes needed both lease-recovery and worker-triggered paths; and the loop diagram
needed its health update after a successful claim. All were verified against
source and corrected.

Smaller corrections cover the execution thread's role, oversized input errors,
stored-template revalidation, required Linux process protection, immediate-child
termination, cross-clock orphan age and ambiguous submission responses.

A focused final Claude consultation completed with exit 0 and found no blockers or
material inaccuracies. It checked the complete architecture document against
worker, job, database, API, metrics, settings, maintenance and storage code, the
entry point, application/configuration/network-policy manifests and Kubernetes
guide. The previous review covered the child, admission and download paths.
Final optional clarifications describe readiness during S3 outages, maintenance
eligibility, pool contention, queue age including retries, and worker liveness.

## Verification and limits

`uv run python scripts/check_docs.py` checks local links, bundled template/data
examples and deployment YAML. `git diff --check` checks patch whitespace.
No new runtime tests are required for these documentation-only changes; the
existing verification workflow runs on push.

HA deployment requirements are recommendations, clearly separated from the
bundled single-replica configuration. Existing single-node recovery/HPA tests do
not certify multi-node availability, dependency failover or production capacity.
Architecture deliberately avoids pinning a library release or schema revision;
implementation history and dependency versions remain in their own records.
