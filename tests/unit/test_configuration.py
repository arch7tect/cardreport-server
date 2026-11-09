"""Operator settings reach the actual execution and deployment boundaries."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast

import pytest

from cardreport_server import render_child, worker
from cardreport_server.settings import Settings

ROOT = Path(__file__).resolve().parents[2]


def test_compose_settings_defaults_and_overrides(tmp_path: Path) -> None:
    # Interpolate using Compose itself, without local .env or inherited app settings.
    environment = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("CARDREPORT_", "COMPOSE_"))
        and k not in {"WORKER_CONCURRENCY", "S3_BUCKET", "S3_PREFIX", "POSTGRES_DB"}
    }

    def config(overrides: dict[str, str]) -> dict[str, Any]:
        env_file = tmp_path / "settings.env"
        env_file.write_text("\n".join(f"{k}={v}" for k, v in overrides.items()))
        result = subprocess.run(
            [
                "docker",
                "compose",
                "--env-file",
                str(env_file),
                "--profile",
                "app",
                "config",
                "--format",
                "json",
            ],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=True,
        )
        return cast(dict[str, Any], json.loads(result.stdout)["services"])

    services = config({})
    for service in ("api", "worker", "migrate"):
        actual = Settings.model_validate(
            {
                k.removeprefix("CARDREPORT_").lower(): v
                for k, v in services[service]["environment"].items()
            }
        )
        assert set(
            "CARDREPORT_" + name.upper()
            for name in Settings.model_fields
            if name != "input_retention"
        ) <= set(services[service]["environment"])
        for name, field in Settings.model_fields.items():
            if not field.is_required():
                assert getattr(actual, name) == field.default, name

    changed = config(
        {
            "CARDREPORT_MAX_ATTEMPTS": "7",
            "CARDREPORT_RENDER_TIMEOUT": "240",
            "CARDREPORT_ATTEMPT_TIMEOUT": "360",
            "CARDREPORT_POLL_SECONDS": "0.25",
            "CARDREPORT_WORKER_CONCURRENCY": "4",
            "WORKER_CONCURRENCY": "6",
            "CARDREPORT_DATABASE_URL": "postgresql://ignored@127.0.0.1/native",
            "CARDREPORT_S3_ENDPOINT": "http://127.0.0.1:9999",
            "CONTAINER_STOP_GRACE": "400s",
        }
    )
    for service in ("api", "worker", "migrate"):
        app = changed[service]["environment"]
        assert app["CARDREPORT_MAX_ATTEMPTS"] == "7"
        assert app["CARDREPORT_RENDER_TIMEOUT"] == "240"
        assert app["CARDREPORT_ATTEMPT_TIMEOUT"] == "360"
        assert app["CARDREPORT_POLL_SECONDS"] == "0.25"
        assert app["CARDREPORT_WORKER_CONCURRENCY"] == "4"
        assert "@postgres:" in app["CARDREPORT_DATABASE_URL"]
        assert app["CARDREPORT_S3_ENDPOINT"] == "http://s3:8333"
    assert changed["worker"]["stop_grace_period"] == "6m40s"
    legacy = config({"WORKER_CONCURRENCY": "6"})
    assert legacy["worker"]["environment"]["CARDREPORT_WORKER_CONCURRENCY"] == "6"


@pytest.mark.parametrize(
    "budget,cap,expected", [(500, 12, 12), (7, 120, 7), (500, 450, 450)]
)
@pytest.mark.parametrize("export_error", [False, True])
def test_child_applies_configured_pdf_budget(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    template_spec: dict[str, object],
    budget: float,
    cap: float,
    expected: float,
    export_error: bool,
) -> None:
    (tmp_path / "template.json").write_text(json.dumps(template_spec))
    (tmp_path / "input").write_text(
        json.dumps(
            {
                "format": "cardreport.data/1",
                "datasets": {
                    "summary": {"columns": ["total"], "rows": [{"total": 34}]}
                },
            }
        )
    )
    (tmp_path / "options.json").write_text(
        json.dumps(
            {
                "input_type": "application/json",
                "output": "pdf",
                "renderer": "chromium",
                "render_deadline": 1000 + budget,
                "render_timeout": cap,
                "data_limits": {},
                "output_limit": 10000,
            }
        )
    )
    from cardreport import Report, ValidationError

    observed: list[float] = []

    def pdf(self: Report, *, timeout: float, renderer: object) -> bytes:
        observed.append(timeout)
        if export_error:
            raise ValidationError("private marker")
        return b"%PDF-test"

    monkeypatch.setattr(Report, "to_pdf", pdf)
    monkeypatch.setattr(time, "monotonic", lambda: 1000)
    monkeypatch.setattr(sys, "argv", ["render_child", str(tmp_path)])
    monkeypatch.setattr(signal, "signal", lambda *_: None)
    render_child.main()
    assert observed == [expected]
    outcome = json.loads((tmp_path / "outcome.json").read_text())
    if export_error:
        assert outcome["code"] == "render_failed"
        assert outcome["stage"] == "render"
        assert "private marker" not in str(outcome)
    else:
        assert outcome == {"ok": True}


def test_worker_health_uses_published_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    health_file = tmp_path / "health.json"
    monkeypatch.setattr(worker, "HEALTH", health_file)
    health_file.write_text(
        json.dumps({"ready": True, "time": time.monotonic() - 70, "max_age": 90})
    )
    assert worker.health()
    health_file.write_text(
        json.dumps({"ready": True, "time": time.monotonic() - 70, "max_age": 60})
    )
    assert not worker.health()
