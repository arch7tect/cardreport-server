"""Small repeatable local sizing observation, not a throughput guarantee."""

import json
import os
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import httpx


def main() -> None:
    project = os.environ["COMPOSE_PROJECT_NAME"]
    assert project.startswith("cardreport-test-")
    identifier = subprocess.check_output(
        [
            "docker",
            "ps",
            "-q",
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--filter",
            "label=com.docker.compose.service=worker",
        ],
        text=True,
    ).split()[0]
    records = []
    with httpx.Client(
        base_url="http://127.0.0.1:" + os.environ["API_PORT"], timeout=30
    ) as client:
        for name in ("reference", "flow", "operations"):
            slug = "measure-" + uuid4().hex
            template = Path(f"examples/{name}_template.json").read_bytes()
            data = Path(f"examples/{name}_data.json").read_bytes()
            response = client.post(
                f"/v1/templates/{slug}/versions",
                content=template,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            code = "import time; from pathlib import Path; p=Path('/sys/fs/cgroup/memory.current'); samples=[]; end=time.monotonic()+8; exec('while time.monotonic()<end:\\n samples.append(int(p.read_text())); time.sleep(.05)'); print(max(samples))"
            monitor = subprocess.Popen(
                ["docker", "exec", identifier, "/app/.venv/bin/python", "-c", code],
                stdout=subprocess.PIPE,
                text=True,
            )
            start = time.monotonic()
            response = client.post(
                "/v1/reports",
                params={"template_id": slug},
                content=data,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            job = response.json()
            while time.monotonic() - start < 120:
                status = client.get(job["status_url"]).json()
                if status["state"] in {"succeeded", "failed"}:
                    break
                time.sleep(0.1)
            elapsed = time.monotonic() - start
            assert status["state"] == "succeeded", status
            content = client.get(job["content_url"])
            content.raise_for_status()
            stdout, _ = monitor.communicate(timeout=12)
            records.append(
                {
                    "workload": name,
                    "input_bytes": len(data),
                    "output_bytes": len(content.content),
                    "submit_to_ready_seconds": round(elapsed, 3),
                    "sampled_peak_container_bytes": int(stdout),
                    "concurrent_reports": 1,
                    "configured_slots": 2,
                }
            )
    Path("local/workload-measurements.json").write_text(json.dumps(records, indent=2))
    print(json.dumps(records, indent=2))


if __name__ == "__main__":
    main()
