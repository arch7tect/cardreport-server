import json
import os
import subprocess
from pathlib import Path

import pytest

from cardreport_server.settings import Settings

pytestmark = pytest.mark.container


@pytest.mark.parametrize(
    "case,expected",
    [
        ("expired", "render_timeout"),
        ("size", "output_too_large"),
        ("overflow", "layout_overflow"),
    ],
)
def test_real_child_limits(
    integration_settings: Settings, case: str, expected: str
) -> None:
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
    root = Path(__file__).resolve().parents[2]
    template = json.loads((root / "examples/flow_template.json").read_text())
    if case == "overflow":
        template["report"]["mode"] = "dashboard"
    payload = {
        "template": template,
        "data": (root / "examples/flow_data.json").read_text(),
        "case": case,
    }
    code = """import json,sys,tempfile,time,subprocess
from pathlib import Path
from cardreport_server.render_child import child_environment
p=json.load(sys.stdin)
with tempfile.TemporaryDirectory() as tmp:
 d=Path(tmp)
 (d/'template.json').write_text(json.dumps(p['template']))
 (d/'input').write_text(p['data'])
 (d/'options.json').write_text(json.dumps({'input_type':'application/json','output':'pdf' if p['case']=='overflow' else 'html','render_deadline':time.monotonic()+(-1 if p['case']=='expired' else 30),'output_limit':1024 if p['case']=='size' else 32000000,'data_limits':{}}))
 subprocess.run([sys.executable,'-m','cardreport_server.render_child',str(d)],env=child_environment(d),check=True,timeout=40)
 print((d/'outcome.json').read_text())
"""
    completed = subprocess.run(
        ["docker", "exec", "-i", identifier, "/app/.venv/bin/python", "-c", code],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        timeout=45,
        check=True,
    )
    assert json.loads(completed.stdout)["code"] == expected
