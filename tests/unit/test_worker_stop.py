import signal
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from cardreport_server.render_child import Cancelled, cancel
from cardreport_server.settings import Settings
from cardreport_server.worker import Running


def test_stop_is_one_shot_and_no_child_has_no_kill_clock() -> None:
    running = Running(Mock(), 100, 80)
    running.stop()
    assert running.cancelled.is_set() and running.stopped_at is None
    child = Mock()
    child.poll.return_value = None
    running.process = child
    running.stop()
    running.stop()
    assert child.terminate.call_count == 1
    assert running.stopped_at is not None


def test_signal_ignores_further_termination() -> None:
    import pytest

    original = signal.getsignal(signal.SIGTERM)
    try:
        with pytest.raises(Cancelled):
            cancel(signal.SIGTERM, None)
        assert signal.getsignal(signal.SIGTERM) == signal.SIG_IGN
    finally:
        signal.signal(signal.SIGTERM, original)


def test_cancelled_child_launch_wakes_supervisor(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib
    import time
    from uuid import uuid4

    from cardreport_server.worker import Worker

    worker = Worker(settings.model_copy(update={"temp_root": tmp_path}))
    database = Mock()
    connection = Mock()
    connection.execute.return_value.fetchone.return_value = {"definition": "{}"}
    context = Mock()
    context.__enter__ = Mock(return_value=connection)
    context.__exit__ = Mock(return_value=False)
    database.pool.connection.return_value = context
    monkeypatch.setattr(worker, "db", database)
    storage = Mock()
    storage.download.side_effect = lambda key, stream, limit: stream.write(b"{}")
    monkeypatch.setattr(worker, "storage", storage)
    attempt = Mock(
        token=uuid4(),
        input_hash=hashlib.sha256(b"{}").hexdigest(),
        input_size=2,
        input_type="application/json",
        output="pdf",
        renderer="chromium",
    )
    running = Running(attempt, time.monotonic() + 120, time.monotonic() + 60)
    child = Mock()
    child.returncode = None
    child.poll.side_effect = lambda: child.returncode

    def launch(*args: object, **kwargs: object) -> Mock:
        running.cancelled.set()
        return child

    def wait() -> None:
        assert running.stopped_at is not None
        worker._wakeups.get_nowait()  # Must arrive before the blocking process.wait().
        child.returncode = -signal.SIGTERM

    child.wait.side_effect = wait
    monkeypatch.setattr(subprocess, "Popen", launch)
    worker.execute(running)
    child.terminate.assert_called_once()
    database.pool.connection.assert_called_once()
