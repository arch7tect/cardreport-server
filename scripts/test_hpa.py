"""Bounded CPU-HPA acceptance in an explicitly selected disposable kind cluster."""

import argparse
import json
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import httpx
from cardreport import Dataset, datasets_to_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--url", default="http://127.0.0.1:18080")
    args = parser.parse_args()
    if not args.context.startswith("kind-cardreport-test"):
        raise SystemExit("Only a dedicated cardreport test cluster is allowed")
    command = [
        "kubectl",
        "--context",
        args.context,
        "--kubeconfig",
        args.kubeconfig,
        "-n",
        "cardreport",
    ]

    def kubectl(*parts: str) -> str:
        return subprocess.check_output([*command, *parts], text=True)

    kubectl(
        "patch",
        "hpa",
        "cardreport-worker",
        "--type=merge",
        "-p",
        '{"spec":{"maxReplicas":2}}',
    )
    slug = "hpa-" + uuid4().hex
    data = datasets_to_json(
        {
            "items": Dataset.from_dicts(
                [{"id": f"ITEM-{i:04d}", "amount": i} for i in range(1000)]
            )
        }
    )
    Path("local").mkdir(exist_ok=True)
    history = []
    with httpx.Client(base_url=args.url, timeout=30) as client:
        response = client.post(
            f"/v1/templates/{slug}/versions",
            content=Path("examples/flow_template.json").read_bytes(),
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        urls = []
        for _ in range(60):
            response = client.post(
                "/v1/reports",
                params={"template_id": slug},
                content=data,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            urls.append(response.json()["status_url"])
        deadline = time.monotonic() + 240
        scaled = False
        while time.monotonic() < deadline:
            hpa = json.loads(kubectl("get", "hpa", "cardreport-worker", "-o", "json"))[
                "status"
            ]
            history.append(hpa)
            scaled = scaled or hpa.get("currentReplicas", 0) > 1
            statuses = [client.get(url).json()["state"] for url in urls]
            if all(s in {"succeeded", "failed"} for s in statuses):
                break
            time.sleep(5)
        Path("local/hpa-evidence.json").write_text(
            json.dumps({"samples": history, "states": statuses}, indent=2)
        )
        assert scaled, "HPA did not actually scale replicas"
        assert all(s == "succeeded" for s in statuses), statuses
        print(f"HPA scaled to two workers; {len(statuses)} reports succeeded")


if __name__ == "__main__":
    main()
