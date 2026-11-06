# Implementation verification — 2026-11-06

Status: local development acceptance complete. No remote, package release or production
installation was created. Commands ran on macOS arm64 with Docker Desktop's Linux
arm64 containers and Python 3.12; no Windows or Linux amd64 execution is claimed.

## Completed evidence

- Ruff and strict mypy passed during each implementation slice.
- 38 unit/real PostgreSQL/S3/TCP tests passed, including response loss after commit,
  infrastructure backoff/cap, stale completion and orphan cursor reset.
- Eleven container tests passed on the final image, including PDF/HTML, YAML, complete long-table rows,
  detached Chromium crash/retry, two workers with two concurrent slots each, active
  SIGTERM drain, and bounded shutdown with blocked maintenance or attempt I/O.
  Combined with the unit/integration lane: 49 passing tests.
- The real-child checks include: expired budget, output cap, genuine
  dashboard overflow. Generated reference and flow PDF pages were visually inspected.
- PostgreSQL 18.0 and SeaweedFS 4.52 image digests pinned; actual authentication,
  put/get/delete and migrations verified. Immutable migration sequence 0001–0004.
- kind 0.31.0, Kubernetes 1.35.0, Metrics Server 0.8.1: actual CPU HPA change from one
  to two worker replicas, all 60 submitted 1000-row reports succeeded.
- Same-pod worker container restart removed only owned UUID attempt leftovers and
  preserved an unrelated marker. Deployment replacement produced a new pod UID.
- NetworkPolicy allowed a labelled client and rejected an unlabelled client; adding
  the label to the rejected client made it succeed. kindnet plus policy-only
  kube-router 2.11.1 were present; no single-controller attribution is claimed.
- Nginx 1.28.3 proxy forwarded incomplete chunked uploads into all four API slots;
  a fifth request returned 429. Reference and flow PDFs also downloaded through it.

## Reviewed corrections

Claude completed S2, S4, S5 and final integration reviews, all exit 0. Accepted
findings are recorded in the dated review documents. Final review identified
migration Job reuse/hardening and documentation/CI omissions; these were repaired.
A narrow final follow-up found no blocker in the shutdown, migration and harness
repairs. A global shutdown deadline also bounds active I/O futures. Raw consultation
replies remain under ignored local/.

The first kind storage fixture incorrectly advertised internal mini-service ports
through an S3-only Service. It was corrected to advertise loopback inside its single
pod; the subsequent 60-report run succeeded. Initial failures are not passing evidence.
Upgrade acceptance paused admission while keeping existing downloads available,
drained the queue, reran the hardened explicit migration Job, deployed the newer
image, and successfully rendered after rolling back to the previous schema-compatible
image. The current image was restored. One proxy call timed out during rollout;
waiting for the actual proxy readiness route before the smoke fixed the acceptance
sequence. This is not a zero-downtime guarantee.

One Docker build encountered a local snapshot-cache error; an isolated no-cache
rebuild succeeded without pruning unrelated images or data.

## Small sizing observation

One report at a time, two configured slots, 50 ms samples of whole-container
`memory.current` (includes page cache), on the same local host:

| Workload | Input bytes | PDF bytes | Submit to ready | Sampled peak |
| --- | ---: | ---: | ---: | ---: |
| Reference | 2204 | 22499 | 2.604 s | 535 MiB |
| Flow, 150 rows | 5537 | 21567 | 1.806 s | 392 MiB |
| Operations charts | 8268 | 26660 | 2.457 s | 530 MiB |

Reproduce with `scripts/measure_workloads.py` inside an isolated test environment.
These are engineering sizing observations, not throughput promises or worst-case
bounds. The 2 GiB/two-slot worker limit gives headroom above this small sample;
large reports and additional concurrency still require measurement. The HPA run
separately exercised two workers under sustained load. Production S3 variants,
multi-node failure, ingress controllers other than this nginx fixture and other
CPU architectures remain unverified.

## Final delivery checks

A fresh Compose project passed the complete integration/container harness. The
app-profile cleanup was corrected and verified to remove its own API/worker too.
Ruff, strict mypy, documentation links/examples, deployment YAML parsing and Kubernetes
server-side dry run passed. Source distribution and wheel builds succeeded. Hosted
GitHub Actions has not run because no remote exists; its commands were exercised locally.

Remaining coverage limits: not every simultaneous DB/S3 outage or timing permutation
has been exhaustively fault-injected. Storage retention is eventual, and downloads
have bounded lifetimes. Production storage/ingress, multi-node Kubernetes, other
architectures and platform-specific native libraries need their own acceptance.

The final image was rebuilt after the last shutdown change; all 11 container cases
passed in 99.10 seconds. Logs and generated examples were preserved before removing
the task-created kind cluster and isolated Compose stack. No unrelated containers,
volumes, images or user datasets were removed. Final Ruff/format, strict mypy,
39 local documentation links/examples and package builds passed.
