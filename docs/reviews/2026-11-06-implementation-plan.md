# Implementation plan review — 2026-11-06

Status: initial and focused reviews complete; both runner processes exited 0.
Scope: implementation sequence, Compose/kind environments, tests/documentation,
and alignment with the reviewed design. No runtime implementation or deployment.

## Initial consultation

The restricted Claude Code runner exited 0, with read markers from the full plan
and design and inspection of README/AGENTS. No commands/edits were performed by
the reviewer. It supported six slices, an early real-PDF container smoke, Compose
for normal work and kind for deployment acceptance. It requested four material
ordering/operations corrections before implementation.

## Dispositions

| Finding | Resolution |
| --- | --- |
| C1: S4 hard-stop depends on S5 recovery | Moved minimal lease reclamation/attempt cap and real Chromium hard-stop/neighbour recovery tests into S4. S5 extends policies and retention. |
| C2: test stacks collide with developer ports/data | Configurable/unpublished test ports; DB/bucket/project test guards; resolve kill targets by project labels and exact container IDs; cleanup only test-owned resources. |
| C3: native worker has no container cleanup boundary | Native worker unsupported in v1; API can run in PyCharm, workers in containers. Compose restarts/healthchecks and service-owned temp cleanup on emptyDir-preserving restart are explicit. |
| C4: schema gate/upgrade/pause ambiguous | Explicit migration, supported-revision startup gate, immutable forward migrations, upgrade tests with existing data, operator pause setting in S5, tested rollback compatibility or forward fix/approved offline restore. |
| Archive race test precedes submission API | Moved to S3 where admission exists. |
| Readiness and local migration commands | Real worker progress healthcheck for --wait; uv Alembic path until container migrate exists. |
| Early milestone leaks/queue age | Pre-S5 builds explicitly isolated development only. |
| Local S3/CORS | Require real credential rejection tests and disabled-CORS check; local S3 does not dictate production provider. |
| Ingress/policy verification | Keep explicit target-context tests; default kind cannot substantiate production ingress or NetworkPolicy enforcement. |

The [plan](../implementation-plan.md) is authoritative for slice acceptance;
[design](../design.md) remains authoritative for service contracts. Container-only
worker support was clarified in both. No runtime security/cleanup guarantee has
been established by documentation review.

## Focused follow-up

Claude reread the revised plan and design, confirmed C1–C4 closed and found no
remaining material blocker. Its verdict was ready for incremental implementation,
starting with S1. This is advisory agreement, not runtime verification.

Final wording suggestions were applied: design rollback now matches schema gates;
S1–S6 is the single authoritative stage checklist; hard fallback exits non-zero
while normal drain exits zero; scaled workers never share temporary roots; migration
runs explicitly, not as an implicit Compose dependency. Status lines are current.

## Planning checks

- Local Markdown links, whitespace, TOML and scaffold Ruff checks pass.
- Docker client, Compose, kind and kubectl are installed; Docker daemon was
  unavailable during the read-only preflight. No containers/clusters were started.
- The plan marks all future Compose/runtime commands as planned, not executable
  features. Pinned images, storage compatibility, migrations and runtime tests
  must be implemented/verified in their assigned slices.
- Exact Compose/profile/kind and storage documentation sources are linked from
  the plan. Local S3 image/version/platform checks are deliberately an S1 gate.

Raw consultation output remains ignored under local/; this record summarizes
findings and dispositions. No remote, push, release or deployment was performed.
