"""Exercise scheduler races and time budgets without wall-clock sleeps or services."""

import time
from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path
from queue import Empty, SimpleQueue
from unittest.mock import Mock
from uuid import uuid4

import pytest
from psycopg import OperationalError

from cardreport_server import jobs
from cardreport_server import worker as module
from cardreport_server.settings import Settings
from cardreport_server.worker import Running, Worker


class Recycled(Exception):
    pass


class Loop:
    def __init__(self, worker: Worker) -> None:
        self.worker = worker
        self.gauge = Mock()
        self.now = 0.0
        self.tokens: SimpleQueue[None] = SimpleQueue()
        self.waits: list[float] = []
        self.started: list[tuple[float, Future[None]]] = []
        self.heartbeats: list[float] = []
        self.on_wait: Callable[[], None] = lambda: None
        self.on_start: Callable[[Future[None]], None] = lambda _: None
        self.maintenance: Future[None] = Future()
        self.maintenance.set_result(None)

    def put(self, item: None) -> None:
        self.tokens.put(item)

    def get_nowait(self) -> None:
        return self.tokens.get_nowait()

    def get(self, *, timeout: float) -> None:
        try:
            return self.tokens.get_nowait()
        except Empty:
            self.on_wait()
        try:
            return self.tokens.get_nowait()
        except Empty:
            assert timeout > 0, "Past deadlines must not busy-spin"
            assert len(self.waits) < 30, "Loop made no progress"
            self.waits.append(timeout)
            self.now += timeout
            raise

    def submit(self, function: object, *args: object) -> Future[None]:
        if not args:
            return self.maintenance
        future: Future[None] = Future()
        self.started.append((self.now, future))
        self.on_start(future)
        return future

    def heartbeat(self, *args: object) -> set[object]:
        self.heartbeats.append(self.now)
        return {r.attempt.token for r in self.worker.active.values()}

    def finish(self) -> None:
        self.worker.stop()
        for _, future in self.started:
            if not future.done():
                future.set_result(None)

    def run(self) -> int:
        return self.worker._supervise(self.gauge)


@pytest.fixture
def loop(settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Loop:
    worker = Worker(settings.model_copy(update={"poll_seconds": 30.0}))
    harness = Loop(worker)
    monkeypatch.setattr(worker, "_wakeups", harness)
    monkeypatch.setattr(time, "monotonic", lambda: harness.now)
    monkeypatch.setattr(module, "HEALTH", tmp_path / "health.json")
    monkeypatch.setattr(worker.db, "close", lambda: None)
    monkeypatch.setattr(jobs, "heartbeat", harness.heartbeat)
    executor = Mock()
    executor.submit.side_effect = harness.submit
    context = Mock()
    context.__enter__ = Mock(return_value=executor)
    context.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(module, "ThreadPoolExecutor", Mock(return_value=context))

    def recycle() -> None:
        raise Recycled

    monkeypatch.setattr(module, "recycle", recycle)
    return harness


def test_fill_slots_then_wake_for_completion(
    loop: Loop, monkeypatch: pytest.MonkeyPatch
) -> None:
    claims = [Mock(token=uuid4()) for _ in range(3)]
    claim = Mock(side_effect=claims)
    monkeypatch.setattr(jobs, "claim", claim)

    def complete_between_inspection_and_wait() -> None:
        assert claim.call_count == 2  # Full worker must not overclaim.
        loop.now = 0.25
        loop.started[0][1].set_result(None)

    loop.on_wait = complete_between_inspection_and_wait

    def on_start(future: Future[None]) -> None:
        if len(loop.started) == 3:
            loop.finish()

    loop.on_start = on_start
    assert loop.run() == 0
    assert [when for when, _ in loop.started] == [0.0, 0.0, 0.25]
    assert not loop.waits
    loop.gauge.set.assert_called_with(0)


def test_completion_before_callback_registration(
    loop: Loop, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jobs, "claim", lambda *_: Mock(token=uuid4()))

    def finish_immediately(future: Future[None]) -> None:
        future.set_result(None)
        if len(loop.started) == 4:
            loop.worker.stop()

    loop.on_start = finish_immediately
    assert loop.run() == 0
    assert len(loop.started) == 4 and not loop.waits


@pytest.mark.parametrize("database_error", [False, True])
def test_empty_queue_and_errors_keep_poll_interval(
    loop: Loop, monkeypatch: pytest.MonkeyPatch, database_error: bool
) -> None:
    loop.worker.settings.maintenance_interval = 5
    claims: list[float] = []

    def claim(*args: object) -> None:
        claims.append(loop.now)
        if len(claims) == 2:
            loop.worker.stop()
        elif database_error:
            raise OperationalError("unavailable")

    monkeypatch.setattr(jobs, "claim", claim)
    assert loop.run() == 0
    assert claims == [0.0, 30.0]
    assert loop.heartbeats == [0.0, 15.0, 30.0]
    assert not loop.started


def test_slow_claims_do_not_starve_heartbeats(
    loop: Loop, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop.worker.settings.worker_concurrency = 4
    loop.worker.settings.heartbeat_seconds = 1

    def claim(*args: object) -> Mock:
        loop.now += 1
        return Mock(token=uuid4())

    monkeypatch.setattr(jobs, "claim", claim)
    loop.on_start = lambda _: loop.finish() if len(loop.started) == 4 else None
    assert loop.run() == 0
    assert [when for when, _ in loop.started] == [1, 2, 3, 4]
    assert loop.heartbeats == [0, 1, 2, 3, 4]
    assert not loop.waits


def test_stop_during_claim_prevents_further_claims(
    loop: Loop, monkeypatch: pytest.MonkeyPatch
) -> None:
    def claim(*args: object) -> Mock:
        loop.worker.stop()
        return Mock(token=uuid4())

    mocked_claim = Mock(side_effect=claim)
    monkeypatch.setattr(jobs, "claim", mocked_claim)
    loop.on_start = lambda future: future.set_result(None)
    assert loop.run() == 0
    assert mocked_claim.call_count == 1


def test_attempt_and_cleanup_deadlines_override_long_poll(
    loop: Loop, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop.worker.settings.worker_concurrency = 1
    child = Mock()
    child.poll.return_value = None
    running = Running(Mock(token=uuid4()), 10, 60, process=child, future=Future())
    loop.worker.active["attempt"] = running
    claim = Mock()
    monkeypatch.setattr(jobs, "claim", claim)
    with pytest.raises(Recycled):
        loop.run()
    assert running.stopped_at == 5
    assert loop.now == 10
    assert loop.waits == [5, 5]
    child.terminate.assert_called_once()
    claim.assert_not_called()


def test_cancelled_io_does_not_spin_on_past_deadline(
    loop: Loop, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop.worker.settings.worker_concurrency = 1
    future: Future[None] = Future()
    running = Running(Mock(token=uuid4()), 6, 60, future=future)
    loop.worker.active["attempt"] = running
    monkeypatch.setattr(jobs, "claim", Mock())

    def stop_after_waiting_past_cancellation() -> None:
        if loop.now >= 15:
            future.set_result(None)
            loop.worker.stop()

    loop.on_wait = stop_after_waiting_past_cancellation
    assert loop.run() == 0
    assert running.cancelled.is_set() and running.stopped_at is None
    assert loop.waits == [1, 14]


def test_shutdown_wakes_when_maintenance_finishes(
    loop: Loop, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop.maintenance = Future()
    monkeypatch.setattr(jobs, "claim", lambda *_: loop.worker.stop())
    loop.on_wait = lambda: loop.maintenance.set_result(None)
    assert loop.run() == 0
    assert not loop.waits
