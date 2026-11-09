# Internal Kubernetes deployment

Use the same image for API, migration and workers. Released multi-platform images
are available from GHCR; see [image installation and digests](../releases.md). Plain manifests are in
[deploy/kubernetes](../../deploy/kubernetes). Replace the development image tag with
an immutable registry digest and set IMAGE_ID to that digest. Provide a Secret named
`cardreport-secrets` with DATABASE_URL/S3_ENDPOINT/S3_ACCESS_KEY/S3_SECRET_KEY, all
prefixed `CARDREPORT_`. Use managed PostgreSQL/S3 in production.

The examples fix the namespace as `cardreport`; change all manifests consistently
if you need another name. Always select an explicit context and namespace. Apply configuration, run the one
migration Job and wait for completion, then apply app Deployments/Service/HPA.
Never let normal API/worker restarts implicitly migrate. See the
[drain/upgrade procedure](operations.md#upgrade-and-rollback).

The example NetworkPolicies allow only labelled client namespaces/pods to reach
API port 8000 and labelled monitoring namespaces to reach worker metrics 9000.
They allow DNS and same-namespace development PostgreSQL/S3. Adapt those destinations
to your actual external services before enabling the policies. Default kind networking
does not establish policy enforcement. Do not interpret manifest validity as a test
of isolation; verify both allowed and denied connections on your target CNI.

Use an internal reverse proxy with request buffering disabled, at least a 16 MiB
body limit, and upload/read deadlines exceeding the service's limits. A port-forward
is useful for debugging but does not test proxy buffering. The service receives a
streaming raw body and streams committed downloads; template registration is bounded
in-memory validation.

See the architecture guide for [high availability](../architecture.md#high-availability)
and [scaling](../architecture.md#scaling), including which production controls
are not included in these example manifests.

## Disposable kind acceptance

Compose remains the everyday development path. kind tests deployment-specific
behavior on one node; they do not establish multi-node resilience or production sizing.
The example dependency overlay stores disposable data in emptyDir and includes
public development credentials. Never apply it to a shared or production cluster.

```sh
mkdir -p local
docker compose --profile app build
kind create cluster --name cardreport-test --config deploy/kind/cluster.yaml --kubeconfig local/kind-kubeconfig --image kindest/node:v1.35.0@sha256:452d707d4862f52530247495d180205e029056831160e22870e37e3f6c1ac31f
kind load docker-image cardreport-server:local --name cardreport-test
kubectl --kubeconfig local/kind-kubeconfig --context kind-cardreport-test apply -f deploy/kubernetes/config.yaml
kubectl --kubeconfig local/kind-kubeconfig --context kind-cardreport-test -n cardreport apply -f deploy/kind/dependencies.yaml
kubectl --kubeconfig local/kind-kubeconfig --context kind-cardreport-test -n cardreport rollout status deployment/cardreport-postgres --timeout=180s
kubectl --kubeconfig local/kind-kubeconfig --context kind-cardreport-test -n cardreport rollout status deployment/cardreport-s3 --timeout=180s
kubectl --kubeconfig local/kind-kubeconfig --context kind-cardreport-test -n cardreport apply -f deploy/kubernetes/migrate.yaml
kubectl --kubeconfig local/kind-kubeconfig --context kind-cardreport-test -n cardreport wait --for=condition=complete job/cardreport-migrate --timeout=120s
kubectl --kubeconfig local/kind-kubeconfig --context kind-cardreport-test -n cardreport apply -f deploy/kubernetes/app.yaml
kubectl --kubeconfig local/kind-kubeconfig --context kind-cardreport-test -n cardreport rollout status deployment/cardreport-api --timeout=180s
kubectl --kubeconfig local/kind-kubeconfig --context kind-cardreport-test -n cardreport rollout status deployment/cardreport-worker --timeout=180s
kubectl --kubeconfig local/kind-kubeconfig --context kind-cardreport-test -n cardreport port-forward service/cardreport-api 18080:8000
```

In another terminal run the Python quickstart with `--url http://127.0.0.1:18080`.
Stop port-forward with Ctrl-C. After completing acceptance, follow
[test cluster cleanup](kubernetes.md#test-cluster-cleanup).

CPU HPA requires Metrics Server. The acceptance environment pins
[Metrics Server 0.8.1](https://github.com/kubernetes-sigs/metrics-server/releases/tag/v0.8.1).
Only for disposable kind, add `--kubelet-insecure-tls` to its Deployment because kind
kubelet certificates lack the expected trust chain. Do not copy that exception into
production. Confirm `kubectl top pods` and actual HPA replica changes under load.

Pods keep separate PID namespaces and a per-pod temporary emptyDir. Workers remove
only their own UUID-named attempt directories after a same-pod container restart.
The init process and 140-second termination grace support bounded drain and detached
Chromium cleanup. Do not enable `shareProcessNamespace` or share worker temp volumes.

For actual results and limits, consult the [verification record](../reviews/2026-11-06-verification.md).

## Additional acceptance checks

Install Metrics Server from the pinned release above, then patch only the kind
Deployment with `--kubelet-insecure-tls`. Once `kubectl top pods` works, run:

```sh
uv run python scripts/test_hpa.py --context kind-cardreport-test --kubeconfig local/kind-kubeconfig
uv run python scripts/test_pod_recovery.py --context kind-cardreport-test --kubeconfig local/kind-kubeconfig
```

The HPA scenario caps this disposable test at two replicas and leaves that cap in
place. Reapply app.yaml to restore its four-replica maximum. These commands generate
synthetic data and restart only explicitly selected test-cluster worker pods.

Apply `deploy/kubernetes/network-policy.yaml` only after installing a policy
controller. The recorded acceptance used policy-only kube-router 2.11.1
(`--run-router=false --run-service-proxy=false --run-firewall=true`) alongside kindnet.
Verify a labelled client succeeds and an unlabelled client fails, then relabel that
same failed client and confirm it succeeds. This distinguishes policy rejection
from a broken client/network. Attribution to an individual controller is unnecessary.

For the optional local internal proxy:

```sh
kubectl --kubeconfig local/kind-kubeconfig --context kind-cardreport-test -n cardreport apply -f deploy/kind/proxy.yaml
kubectl --kubeconfig local/kind-kubeconfig --context kind-cardreport-test -n cardreport port-forward service/cardreport-proxy 18081:8080
# In another terminal:
uv run python scripts/test_proxy_streaming.py
uv run python examples/client.py --url http://127.0.0.1:18081
```

This traverses nginx before the API. Incomplete chunked uploads occupy all API
upload slots, proving forwarding starts before the complete request arrives.
Nginx disables both request and response buffering, uses upstream HTTP/1.1 and
bounded timeouts. The kind proxy is an acceptance fixture, not a public ingress.
For repeat migrations, confirm/save the completed Job's logs, delete that exact
completed Job, then reapply migrate.yaml and wait for completion before deployments.


## Test cluster cleanup

The acceptance scripts leave the cluster running for inspection; they do not
clean it up automatically. After testing, delete the dedicated `cardreport-test`
cluster created above. Run these commands from the project root, using the same
container runtime that created the cluster.

1. Stop any API/proxy `kubectl port-forward` processes with Ctrl-C. Confirm the
   intended cluster name:

   ```sh
   kind get clusters
   ```

2. Save any reports or other test data you need before deletion. Export diagnostic
   logs to a new directory and check that the export succeeds:

   ```sh
   mkdir -p local
   kind export logs --name cardreport-test "$(mktemp -d local/kind-logs.XXXXXX)"
   ```

   Logs are not a backup of PostgreSQL or S3 data. Keep the exported logs and
   existing evidence such as `local/hpa-evidence.json` when investigating failures.

3. Delete only this disposable test cluster:

   ```sh
   kind delete cluster --name cardreport-test --kubeconfig local/kind-kubeconfig
   ```

   This removes its node containers and all in-cluster resources, including
   Metrics Server, the test PostgreSQL/S3 instances and their `emptyDir` data.
   It also removes this cluster's entries from the specified kubeconfig.
   Other kind clusters, the separate Compose stack, host Docker images and saved
   files in `local/` are not removed. Do not use Docker-wide pruning or delete
   Compose volumes as part of this cleanup.

4. Verify that `cardreport-test` no longer appears:

   ```sh
   kind get clusters
   ```

To run acceptance again, repeat the cluster creation, dependency deployment and
migration steps above. Deleting only the `cardreport` namespace would leave
cluster-wide additions such as Metrics Server behind, so it is not a complete
reset of this disposable environment.
