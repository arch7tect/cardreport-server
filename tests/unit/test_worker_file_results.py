import hashlib
import json
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest

from cardreport_server import jobs
from cardreport_server import worker as module
from cardreport_server.settings import Settings


@pytest.mark.parametrize(
    "case",
    [
        "output_limit",
        "snapshot_limit",
        "invalid_diagnostics",
        "success",
        "layout_valid",
        "layout_invalid",
        "layout_wrong_code",
    ],
)
def test_file_diagnostics_are_advisory_and_survive_failure(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    worker = module.Worker(
        settings.model_copy(update={"temp_root": tmp_path, "output_limit": 1024})
    )
    db = MagicMock()
    db.pool.connection.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = {
        "definition": "{}"
    }
    monkeypatch.setattr(worker, "db", db)
    store = Mock(prefix="test/")
    store.download.side_effect = lambda key, stream, limit: stream.write(b"{}")
    monkeypatch.setattr(worker, "storage", store)
    attempt = Mock(
        token=uuid4(),
        report_id=uuid4(),
        input_hash=hashlib.sha256(b"{}").hexdigest(),
        input_size=2,
        input_type="application/json",
        output="html",
        renderer="chromium",
    )
    files = [{"id": 1, "status": "parsed", "datasets": ["summary"], "error": None}]

    def launch(*args: object, **kwargs: object) -> Mock:
        directory = tmp_path / ("attempt-" + str(attempt.token))
        outcome: dict[str, object] = {"ok": True}
        if case.startswith("layout_"):
            outcome = {
                "code": "layout_overflow"
                if case != "layout_wrong_code"
                else "invalid_data",
                "stage": "render",
                "message": "safe",
                "diagnostic": {"reason": "label_overlap", "path": "blocks.0"},
            }
            if case == "layout_invalid":
                outcome["diagnostic"] = {
                    "reason": "label_overlap",
                    "path": "PRIVATE_VALUE",
                }
        (directory / "outcome.json").write_text(json.dumps(outcome))
        (directory / "result").write_bytes(
            b"x" * (1025 if case == "output_limit" else 1)
        )
        (directory / "data.json").write_bytes(b"{}")
        (directory / "files.json").write_text(
            "invalid" if case == "invalid_diagnostics" else json.dumps(files)
        )
        process = Mock(returncode=0)
        process.poll.return_value = 0
        return process

    monkeypatch.setattr(subprocess, "Popen", launch)
    if case == "snapshot_limit":
        monkeypatch.setattr(module, "SNAPSHOT_LIMIT", 1)
    finish = Mock(return_value=True)
    monkeypatch.setattr(jobs, "finish", finish)
    worker.execute(
        module.Running(attempt, time.monotonic() + 120, time.monotonic() + 60)
    )
    finish.assert_called_once()
    assert finish.call_args.kwargs["files"] == (
        None if case == "invalid_diagnostics" else files
    )
    if case.startswith("layout_"):
        error = finish.call_args.kwargs["error"]
        assert ("diagnostic" in error) == (case == "layout_valid")
        assert "PRIVATE_VALUE" not in str(error)
    elif case in {"output_limit", "snapshot_limit"}:
        assert (
            finish.call_args.kwargs["error"]["code"]
            == {
                "output_limit": "output_too_large",
                "snapshot_limit": "data_snapshot_too_large",
            }[case]
        )
    else:
        assert "result" in finish.call_args.kwargs
