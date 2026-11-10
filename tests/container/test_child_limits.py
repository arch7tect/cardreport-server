import json
import os
import subprocess
from pathlib import Path

import pytest

from cardreport_server.settings import Settings

pytestmark = pytest.mark.container


@pytest.mark.parametrize(
    "case,renderer,expected",
    [
        ("long_budget", "chromium", "ok"),
        ("long_budget", "weasyprint", "ok"),
        ("expired", "chromium", "render_timeout"),
        ("expired", "weasyprint", "render_timeout"),
        ("size", "chromium", "output_too_large"),
        ("size", "weasyprint", "output_too_large"),
        ("overflow", "chromium", "layout_overflow"),
        ("overflow", "weasyprint", "layout_overflow"),
        # An oversized natural table is a layout error, not a renderer crash.
        ("large_table", "weasyprint", "layout_overflow"),
    ],
)
def test_real_child_limits(
    integration_settings: Settings,
    case: str,
    expected: str,
    renderer: str,
    template_spec: dict[str, object],
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
    name = (
        "reference"
        if case == "long_budget" or (case == "size" and renderer == "weasyprint")
        else "flow"
    )
    template = json.loads((root / f"examples/{name}_template.json").read_text())
    data = (root / f"examples/{name}_data.json").read_text()
    if case in {"overflow", "large_table"}:
        template["report"]["mode"] = "dashboard"
    if case == "overflow" and renderer == "weasyprint":
        template = json.loads(json.dumps(template_spec))
        template["report"]["blocks"] = [
            {
                "type": "row",
                "height_mm": 5,
                "children": template["report"]["blocks"],
            }
        ]
        data = json.dumps(
            {
                "format": "cardreport.data/1",
                "datasets": {
                    "summary": {"columns": ["total"], "rows": [{"total": 34}]}
                },
            }
        )
    payload = {
        "template": template,
        "data": data,
        "renderer": renderer,
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
 (d/'options.json').write_text(json.dumps({'input_type':'application/json','renderer':p['renderer'],'output':'pdf' if p['case'] in ('overflow','large_table','long_budget') else 'html','render_timeout':450 if p['case']=='long_budget' else 30,'render_deadline':time.monotonic()+(-1 if p['case']=='expired' else 500 if p['case']=='long_budget' else 30),'output_limit':1024 if p['case']=='size' else 32000000,'data_limits':{}}))
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
    outcome = json.loads(completed.stdout)
    if expected == "ok":
        assert outcome == {"ok": True}
    else:
        assert outcome["code"] == expected
        if expected == "layout_overflow":
            assert outcome["diagnostic"]["path"].startswith(
                ("blocks.", "pages.", "report")
            )
            assert "text" not in outcome["diagnostic"]
