"""Blocked background work cannot turn executor shutdown into an unbounded join."""

import os
import subprocess
import time

import pytest

from cardreport_server.settings import Settings

pytestmark = pytest.mark.container


@pytest.mark.parametrize("blocked_stage", ["maintenance", "attempt_io"])
def test_background_work_cannot_exceed_shutdown_budget(
    integration_settings: Settings,
    blocked_stage: str,
) -> None:
    assert os.environ["COMPOSE_PROJECT_NAME"].startswith("cardreport-test-")
    code = """import time
from cardreport_server.settings import Settings
from cardreport_server.worker import Worker
from cardreport_server import jobs, maintenance
settings=Settings(database_url='postgresql://test:test@localhost/test',s3_endpoint='http://localhost:8333',s3_access_key='test',s3_secret_key='test',s3_bucket='unit-test',shutdown_grace=2,poll_seconds=30)
worker=Worker(settings)
worker.db.open=lambda: None
worker.db.close=lambda: None
worker.storage.check=lambda: None
jobs.claim=lambda *args: None
jobs.reap=lambda *args: 0
maintenance.OrphanSweep.run=lambda *args: None
def blocked(*args):
 worker.stop()
 time.sleep(30)
maintenance.maintain=blocked
if STAGE == 'attempt_io':
 from types import SimpleNamespace
 from uuid import uuid4
 maintenance.maintain=lambda *args: None
 claimed=iter([SimpleNamespace(token=uuid4()),None])
 jobs.claim=lambda *args: next(claimed,None)
 worker.execute=blocked
worker.run()
"""
    code = code.replace("STAGE", repr(blocked_stage))
    start = time.monotonic()
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--label",
            "cardreport-test=shutdown-budget",
            "cardreport-server:local",
            "/app/.venv/bin/python",
            "-c",
            code,
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 70, (result.stdout, result.stderr)
    assert time.monotonic() - start < 15
