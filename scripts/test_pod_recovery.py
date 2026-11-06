"""Restart/replacement acceptance restricted to a disposable kind test cluster."""

import argparse
import json
import subprocess
import time
from uuid import uuid4


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    parser.add_argument("--kubeconfig", required=True)
    args = parser.parse_args()
    assert args.context.startswith("kind-cardreport-test")
    base = [
        "kubectl",
        "--context",
        args.context,
        "--kubeconfig",
        args.kubeconfig,
        "-n",
        "cardreport",
    ]

    def kubectl(*parts: str) -> str:
        return subprocess.check_output([*base, *parts], text=True)

    pod = json.loads(
        kubectl("get", "pods", "-l", "app=cardreport,role=worker", "-o", "json")
    )["items"][0]
    name = pod["metadata"]["name"]
    uid = pod["metadata"]["uid"]
    before = pod["status"]["containerStatuses"][0]["restartCount"]
    marker = str(uuid4())
    code = f"from pathlib import Path; import psutil,os,signal; d=Path('/tmp/cardreport-worker/attempt-{marker}'); d.mkdir(); (d/'leftover').write_text('test'); Path('/tmp/cardreport-worker/keep-{marker}').write_text('test'); p=next(p for p in psutil.process_iter(['cmdline']) if (p.info['cmdline'] or [])[1:4]==['-m','cardreport_server','worker']); os.kill(p.pid,signal.SIGKILL)"
    kubectl("exec", name, "--", "/app/.venv/bin/python", "-c", code)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        current = json.loads(kubectl("get", "pod", name, "-o", "json"))
        status = current["status"].get("containerStatuses", [{}])[0]
        if status.get("restartCount", 0) > before and status.get("ready"):
            break
        time.sleep(1)
    assert (
        current["metadata"]["uid"] == uid
        and status.get("restartCount", 0) > before
        and status.get("ready")
    )
    check = f"from pathlib import Path; assert not Path('/tmp/cardreport-worker/attempt-{marker}').exists(); p=Path('/tmp/cardreport-worker/keep-{marker}'); assert p.read_text()=='test'; p.unlink(); print('Owned leftovers removed; unrelated marker preserved')"
    print(kubectl("exec", name, "--", "/app/.venv/bin/python", "-c", check).strip())
    kubectl("delete", "pod", name, "--wait=true", "--timeout=160s")
    kubectl("rollout", "status", "deployment/cardreport-worker", "--timeout=180s")
    pods = json.loads(
        kubectl("get", "pods", "-l", "app=cardreport,role=worker", "-o", "json")
    )["items"]
    assert all(p["metadata"]["uid"] != uid for p in pods)
    print("Container restart in same pod and Deployment replacement passed")


if __name__ == "__main__":
    main()
