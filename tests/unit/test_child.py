from pathlib import Path

import pytest

from cardreport_server.render_child import child_environment


def test_child_environment_is_allowlisted(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "CARDREPORT_DATABASE_URL",
        "AWS_SECRET_ACCESS_KEY",
        "CARDREPORT_S3_SECRET_KEY",
        "PYTHONPATH",
        "LD_PRELOAD",
        "HTTP_PROXY",
    ):
        monkeypatch.setenv(key, "private-marker")
    environment = child_environment(Path("/tmp/attempt"))
    assert "private-marker" not in str(environment)
    assert environment["HOME"] == "/tmp/attempt"
