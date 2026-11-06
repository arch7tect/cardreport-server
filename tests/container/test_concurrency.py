import json
import os
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from cardreport_server.settings import Settings

pytestmark = pytest.mark.container


def test_two_workers_two_slots(integration_settings: Settings) -> None:
    project = os.environ["COMPOSE_PROJECT_NAME"]
    assert project.startswith("cardreport-test-")
    subprocess.run(
        [
            "docker",
            "compose",
            "--profile",
            "app",
            "up",
            "-d",
            "--wait",
            "--scale",
            "worker=2",
            "worker",
        ],
        check=True,
    )
    watchers: list[subprocess.Popen[str]] = []
    ids = subprocess.check_output(
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
    ).split()
    assert len(ids) == 2
    watch = """import psutil,time,json
seen=set();end=time.monotonic()+25
while time.monotonic()<end:
 for p in psutil.process_iter(['pid','cmdline']):
  try:
   a=p.info['cmdline'] or []
   if a[1:3]==['-m','cardreport_server.render_child'] and p.pid not in seen:
    p.suspend();seen.add(p.pid)
  except (psutil.NoSuchProcess,psutil.AccessDenied): pass
 if len(seen)==2:
  time.sleep(1)
  print(json.dumps(sorted(seen)),flush=True);raise SystemExit(0)
 time.sleep(.005)
raise SystemExit(2)
"""
    resume = "import psutil; [(p.resume()) for p in psutil.process_iter(['cmdline']) if (p.info['cmdline'] or [])[1:3]==['-m','cardreport_server.render_child']]"
    try:
        for identifier in ids:
            watchers.append(
                subprocess.Popen(
                    [
                        "docker",
                        "exec",
                        identifier,
                        "/app/.venv/bin/python",
                        "-c",
                        watch,
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            )
        root = Path(__file__).resolve().parents[2]
        slug = "concurrent-" + uuid4().hex
        with httpx.Client(
            base_url="http://127.0.0.1:" + os.environ["API_PORT"], timeout=20
        ) as client:
            assert (
                client.post(
                    f"/v1/templates/{slug}/versions",
                    content=(root / "examples/reference_template.json").read_bytes(),
                    headers={"Content-Type": "application/json"},
                ).status_code
                == 201
            )
            urls = []
            for _ in range(4):
                response = client.post(
                    "/v1/reports",
                    params={"template_id": slug},
                    content=(root / "examples/reference_data.json").read_bytes(),
                    headers={"Content-Type": "application/json"},
                )
                assert response.status_code == 202
                urls.append(response.json()["status_url"])
            for watcher in watchers:
                out, err = watcher.communicate(timeout=30)
                assert watcher.returncode == 0, (out, err)
                assert len(json.loads(out)) == 2
            assert all(client.get(url).json()["state"] == "running" for url in urls)
            subprocess.run(["docker", "kill", "--signal", "TERM", ids[0]], check=True)
            for identifier in ids:
                subprocess.run(
                    [
                        "docker",
                        "exec",
                        identifier,
                        "/app/.venv/bin/python",
                        "-c",
                        resume,
                    ],
                    check=True,
                )
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                states = [client.get(url).json() for url in urls]
                if all(s["state"] == "succeeded" for s in states):
                    break
                time.sleep(0.2)
            assert all(
                s["state"] == "succeeded" and s["attempts"] == 1 for s in states
            ), states
            stop_deadline = time.monotonic() + 15
            while time.monotonic() < stop_deadline:
                stopped = json.loads(
                    subprocess.check_output(["docker", "inspect", ids[0]], text=True)
                )[0]["State"]
                if not stopped["Running"]:
                    break
                time.sleep(0.1)
            assert not stopped["Running"] and stopped["ExitCode"] == 0, stopped
    finally:
        for identifier in ids:
            subprocess.run(
                ["docker", "exec", identifier, "/app/.venv/bin/python", "-c", resume],
                check=False,
            )
        for watcher in watchers:
            if watcher.poll() is None:
                watcher.terminate()
        subprocess.run(
            [
                "docker",
                "compose",
                "--profile",
                "app",
                "up",
                "-d",
                "--scale",
                "worker=1",
                "worker",
            ],
            check=True,
        )
