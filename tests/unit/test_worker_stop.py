import signal
from unittest.mock import Mock

from cardreport_server.render_child import Cancelled, cancel
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
