"""Fault injection stays outside production code and targets exact test containers."""

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


def docker(*args: str) -> str:
    return subprocess.check_output(["docker", *args], text=True)


def test_detached_renderer_container_recovery(
    integration_settings: Settings, tmp_path: Path
) -> None:
    project = os.environ["COMPOSE_PROJECT_NAME"]
    assert project.startswith("cardreport-test-")
    ids = docker(
        "ps",
        "-q",
        "--filter",
        f"label=com.docker.compose.project={project}",
        "--filter",
        "label=com.docker.compose.service=worker",
    ).split()
    assert len(ids) == 1, "Run fault scenario before scaling worker replicas"
    identifier = ids[0]
    inspection = json.loads(docker("inspect", identifier))[0]
    assert inspection["Config"]["Labels"]["com.docker.compose.project"] == project
    before = inspection["RestartCount"]
    # Observe real Chromium descendants, then kill their immediate attempt parent.
    # The supervisor must recycle even if a detached renderer outlives that parent.
    watcher = """import psutil,time,os,signal,json
end=time.monotonic()+30
while time.monotonic()<end:
 for p in psutil.process_iter(['pid','cmdline']):
  try:
   args=p.info['cmdline'] or []
   if len(args)>2 and args[1:3]==['-m','cardreport_server.render_child']:
    children=p.children(recursive=True)
    chrome=[c for c in children if 'chrome' in c.name()]
    if chrome:
     for c in children:
      try: c.suspend()
      except psutil.NoSuchProcess: pass
     print(json.dumps({'parent':p.pid,'descendants':[c.pid for c in children]}),flush=True)
     os.kill(p.pid,signal.SIGKILL)
     raise SystemExit(0)
  except (psutil.NoSuchProcess,psutil.AccessDenied): pass
 time.sleep(.005)
raise SystemExit(2)
"""
    watcher_process = subprocess.Popen(
        ["docker", "exec", identifier, "/app/.venv/bin/python", "-c", watcher],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    root = Path(__file__).resolve().parents[2]
    slug = "containment-" + uuid4().hex
    with httpx.Client(
        base_url="http://127.0.0.1:" + os.environ["API_PORT"], timeout=20
    ) as client:
        response = client.post(
            f"/v1/templates/{slug}/versions",
            content=(root / "examples/reference_template.json").read_bytes(),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201
        response = client.post(
            "/v1/reports",
            params={"template_id": slug},
            content=(root / "examples/reference_data.json").read_bytes(),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 202
        job = response.json()
        stdout, stderr = watcher_process.communicate(timeout=35)
        assert watcher_process.returncode == 0, (stdout, stderr)
        assert json.loads(stdout)["descendants"]
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            state = client.get(job["status_url"]).json()
            if state["state"] in {"succeeded", "failed"}:
                break
            time.sleep(0.5)
        assert state["state"] == "succeeded", state
        assert state["attempts"] == 2, state
        after = json.loads(docker("inspect", identifier))[0]
        assert after["RestartCount"] > before
        assert client.get(job["content_url"]).content.startswith(b"%PDF-")
        # New PID namespace and completed attempt leave no browser behind.
        code = "import psutil,json; print(json.dumps([p.pid for p in psutil.process_iter(['name']) if 'chrome' in (p.info['name'] or '') and p.status()!='zombie']))"
        assert (
            json.loads(docker("exec", identifier, "/app/.venv/bin/python", "-c", code))
            == []
        )
        assert (
            docker(
                "exec",
                identifier,
                "/app/.venv/bin/python",
                "-c",
                "from pathlib import Path; print(len(list(Path('/tmp/cardreport-worker').glob('attempt-*'))))",
            ).strip()
            == "0"
        )
