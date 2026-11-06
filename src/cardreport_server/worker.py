"""Bounded slots, independent leases and container-scoped process containment."""

import hashlib
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path
from queue import Empty, SimpleQueue
from uuid import UUID, uuid4

from botocore.exceptions import BotoCoreError, ClientError
from prometheus_client import Gauge, start_http_server
from psycopg import InterfaceError, OperationalError
from psycopg_pool import PoolTimeout

from . import jobs
from .db import Database
from .render_child import child_environment
from .settings import Settings
from .storage import Storage

log = logging.getLogger(__name__)
HEALTH = Path("/tmp/cardreport-worker-health.json")


@dataclass
class Running:
    attempt: jobs.Attempt
    deadline: float
    lease_ok_until: float
    cancelled: threading.Event = field(default_factory=threading.Event)
    process: subprocess.Popen[bytes] | None = None
    stopped_at: float | None = None
    future: Future[None] | None = None

    def stop(self) -> None:
        self.cancelled.set()
        process = self.process
        if self.stopped_at is None and process is not None and process.poll() is None:
            try:
                process.terminate()
                self.stopped_at = time.monotonic()
            except ProcessLookupError:
                pass


def recycle() -> None:
    log.error("Worker containment fallback; recycling the entire container")
    os._exit(70)


class Worker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db = Database(settings)
        self.storage = Storage(settings)
        self.stopping = threading.Event()
        self.broken = threading.Event()
        self.active: dict[str, Running] = {}
        # CPython SimpleQueue.put is reentrant when a signal interrupts get().
        self._wakeups: SimpleQueue[None] = SimpleQueue()

    def stop(self) -> None:
        self.stopping.set()
        self._wakeups.put(None)

    def execute(self, running: Running) -> None:
        attempt = running.attempt
        directory = self.settings.temp_root / ("attempt-" + str(attempt.token))
        try:
            directory.mkdir(mode=0o700)
            with self.db.pool.connection() as conn:
                row = conn.execute(
                    "SELECT definition::text FROM template_versions WHERE template_id=%s AND version=%s",
                    (attempt.template_id, attempt.template_version),
                ).fetchone()
            assert row is not None
            (directory / "template.json").write_text(row["definition"])
            with (directory / "input").open("wb") as stream:
                size = self.storage.download(
                    attempt.input_key, stream, self.settings.input_limit
                )
            digest = hashlib.sha256((directory / "input").read_bytes()).hexdigest()
            if size != attempt.input_size or digest != attempt.input_hash:
                self.complete(
                    attempt,
                    {
                        "code": "input_integrity",
                        "stage": "download",
                        "message": "Stored input failed its integrity check",
                    },
                )
                return
            remaining = (
                running.deadline
                - time.monotonic()
                - self.settings.cleanup_grace
                - self.settings.io_timeout * 4
            )
            if running.cancelled.is_set():
                return
            if remaining <= 0:
                self.complete(
                    attempt,
                    {
                        "code": "render_timeout",
                        "stage": "render",
                        "message": "Report execution exceeded its time budget",
                    },
                )
                return
            (directory / "options.json").write_text(
                json.dumps(
                    {
                        "input_type": attempt.input_type,
                        "output": attempt.output,
                        "renderer": attempt.renderer,
                        "render_deadline": running.deadline
                        - self.settings.cleanup_grace
                        - self.settings.io_timeout * 4,
                        "data_limits": {
                            "max_rows": self.settings.data_max_rows,
                            "max_cells": self.settings.data_max_cells,
                            "max_json_bytes": self.settings.input_limit,
                        },
                        "output_limit": self.settings.output_limit,
                    }
                )
            )
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "cardreport_server.render_child",
                    str(directory),
                ],
                env=child_environment(directory),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            running.process = process
            if running.cancelled.is_set():
                running.stop()
                self._wakeups.put(None)
            process.wait()
            if running.cancelled.is_set() and process.returncode == -signal.SIGTERM:
                return
            if process.returncode != 0 or not (directory / "outcome.json").exists():
                # A dead parent may leave detached Chromium alive. Only the container is a safe boundary.
                recycle()
            outcome = json.loads((directory / "outcome.json").read_text())
            if running.cancelled.is_set():
                return
            if outcome.get("code") == "renderer_unavailable":
                self.broken.set()
                self._wakeups.put(None)
                jobs.retry(self.db, self.settings, attempt, "renderer_unavailable")
                return
            if not outcome.get("ok"):
                internal_type = outcome.pop("internal_type", None)
                if internal_type is not None:
                    log.error(
                        "Internal render error %s (%s)",
                        outcome.get("id"),
                        internal_type,
                    )
                self.complete(attempt, outcome)
                return
            result = directory / "result"
            size = result.stat().st_size
            if size > self.settings.output_limit:
                self.complete(
                    attempt,
                    {
                        "code": "output_too_large",
                        "stage": "render",
                        "message": "Report exceeds the output size limit",
                    },
                )
                return
            key = (
                self.storage.prefix
                + f"results/{attempt.report_id}/{attempt.token}.{attempt.output}"
            )
            self.storage.put(
                key,
                result,
                "application/pdf"
                if attempt.output == "pdf"
                else "text/html; charset=utf-8",
            )
            if not running.cancelled.is_set():
                jobs.finish(
                    self.db,
                    attempt,
                    result={
                        "key": key,
                        "size": size,
                        "hash": hashlib.sha256(result.read_bytes()).hexdigest(),
                    },
                    engine_version=version("cardreport"),
                    image_id=self.settings.image_id,
                    service_version=version("cardreport-server"),
                )
        except Exception as error:
            correlation_id = uuid4().hex
            log.warning(
                "Attempt interruption %s (%s)", correlation_id, type(error).__name__
            )
            if not running.cancelled.is_set():
                try:
                    if isinstance(
                        error,
                        (
                            BotoCoreError,
                            ClientError,
                            OperationalError,
                            InterfaceError,
                            PoolTimeout,
                            OSError,
                        ),
                    ):
                        jobs.retry(self.db, self.settings, attempt)
                    else:
                        self.complete(
                            attempt,
                            {
                                "code": "internal_error",
                                "stage": "worker",
                                "message": "Internal report execution error",
                                "id": correlation_id,
                            },
                        )
                except Exception:
                    pass  # An expired lease is recovered by any healthy supervisor.
        finally:
            if running.process is not None and running.process.poll() is None:
                running.stop()
                try:
                    running.process.wait(timeout=self.settings.cleanup_grace)
                except subprocess.TimeoutExpired:
                    recycle()
            shutil.rmtree(directory, ignore_errors=True)

    def complete(self, attempt: jobs.Attempt, error: dict[str, object]) -> None:
        jobs.finish(
            self.db,
            attempt,
            error=error | {"retryable": False},
            engine_version=version("cardreport"),
            image_id=self.settings.image_id,
            service_version=version("cardreport-server"),
        )

    def run(self) -> int:
        HEALTH.unlink(missing_ok=True)
        if (
            not Path("/.dockerenv").exists()
            and not Path("/var/run/secrets/kubernetes.io").exists()
            and os.environ.get("CARDREPORT_CONTAINER") != "1"
        ):
            raise RuntimeError("Workers must run inside the documented container")
        import ctypes

        if ctypes.CDLL(None, use_errno=True).prctl(4, 0, 0, 0, 0) != 0:
            raise RuntimeError("Cannot protect supervisor credentials")
        self.settings.temp_root.mkdir(parents=True, exist_ok=True)
        # This root is exclusive to one container; only our UUID-named leftovers are owned.
        for path in self.settings.temp_root.glob("attempt-*"):
            try:
                UUID(path.name.removeprefix("attempt-"))
            except ValueError:
                continue
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
        self.db.open()
        self.storage.check()
        with subprocess.Popen(
            [sys.executable, "-m", "cardreport_server", "smoke"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=child_environment(self.settings.temp_root),
        ) as smoke:
            try:
                if smoke.wait(timeout=75) != 0:
                    return 78
            except subprocess.TimeoutExpired:
                recycle()
        signal.signal(signal.SIGTERM, lambda *_: self.stop())
        signal.signal(signal.SIGINT, lambda *_: self.stop())

        slots = Gauge("cardreport_worker_active_slots", "Active slots in this worker")
        start_http_server(9000)
        return self._supervise(slots)

    def _supervise(self, slots: Gauge) -> int:
        next_claim = 0.0
        next_heartbeat = 0.0
        next_maintenance = 0.0
        stop_deadline: float | None = None
        from .maintenance import OrphanSweep, maintain

        sweep = OrphanSweep()

        def maintenance() -> None:
            jobs.reap(self.db, self.settings)
            maintain(self.db, self.storage, self.settings)
            sweep.run(self.db, self.storage, self.settings)

        maintenance_future: Future[None] | None = None
        with ThreadPoolExecutor(
            max_workers=self.settings.worker_concurrency + 1
        ) as executor:
            try:
                while True:
                    # Drain before observing state, so completions before wait are not lost.
                    while True:
                        try:
                            self._wakeups.get_nowait()
                        except Empty:
                            break
                    claimed = False
                    now = time.monotonic()
                    if (
                        self.stopping.is_set() or self.broken.is_set()
                    ) and stop_deadline is None:
                        stop_deadline = now + self.settings.shutdown_grace
                    if stop_deadline is not None and now >= stop_deadline:
                        recycle()
                    for key, running in list(self.active.items()):
                        if running.future is not None and running.future.done():
                            try:
                                running.future.result()
                            except BaseException:
                                recycle()
                            del self.active[key]
                            next_claim = 0.0
                            continue
                        if now >= min(
                            running.deadline, running.lease_ok_until
                        ) - self.settings.cleanup_grace or (
                            stop_deadline is not None
                            and now >= stop_deadline - self.settings.cleanup_grace
                        ):
                            running.stop()
                        if (
                            running.stopped_at is not None
                            and running.process is not None
                            and running.process.poll() is None
                            and now >= running.stopped_at + self.settings.cleanup_grace
                        ):
                            recycle()
                    if now >= next_heartbeat:
                        heartbeat_start = time.monotonic()
                        try:
                            owned: set[UUID] | None = jobs.heartbeat(
                                self.db,
                                self.settings,
                                [r.attempt for r in self.active.values()],
                            )
                        except Exception:
                            owned = None
                        if owned is not None:
                            for running in self.active.values():
                                if running.attempt.token not in owned:
                                    running.stop()
                                else:
                                    running.lease_ok_until = min(
                                        running.deadline,
                                        heartbeat_start + self.settings.lease_seconds,
                                    )
                        next_heartbeat = (
                            time.monotonic() + self.settings.heartbeat_seconds
                        )
                    if stop_deadline is None:
                        try:
                            if now >= next_maintenance and (
                                maintenance_future is None or maintenance_future.done()
                            ):
                                if maintenance_future is not None:
                                    try:
                                        maintenance_future.result()
                                    except Exception:
                                        log.warning(
                                            "Maintenance dependency unavailable"
                                        )
                                maintenance_future = executor.submit(maintenance)
                                maintenance_future.add_done_callback(
                                    lambda _: self._wakeups.put(None)
                                )
                                next_maintenance = (
                                    time.monotonic()
                                    + self.settings.maintenance_interval
                                )
                            if (
                                len(self.active) < self.settings.worker_concurrency
                                and time.monotonic() >= next_claim
                                and not self.stopping.is_set()
                                and not self.broken.is_set()
                            ):
                                claim_start = time.monotonic()
                                attempt = jobs.claim(self.db, self.settings)
                                if attempt is None:
                                    next_claim = (
                                        time.monotonic() + self.settings.poll_seconds
                                    )
                                else:
                                    # DB timestamps provide the budget without assuming host/DB wall clocks agree.
                                    running = Running(
                                        attempt,
                                        claim_start + self.settings.attempt_timeout,
                                        claim_start + self.settings.lease_seconds,
                                    )
                                    running.future = executor.submit(
                                        self.execute, running
                                    )
                                    self.active[str(attempt.token)] = running
                                    running.future.add_done_callback(
                                        lambda _: self._wakeups.put(None)
                                    )
                                    claimed = True
                        except Exception as error:
                            next_claim = time.monotonic() + self.settings.poll_seconds
                            log.warning(
                                "Worker dependency unavailable (%s)",
                                type(error).__name__,
                            )
                    slots.set(len(self.active))
                    HEALTH.write_text(
                        json.dumps(
                            {
                                "time": time.monotonic(),
                                "ready": not self.broken.is_set(),
                                "active": len(self.active),
                            }
                        )
                    )
                    if stop_deadline is not None and not self.active:
                        if maintenance_future is None or maintenance_future.done():
                            break
                        if time.monotonic() >= stop_deadline:
                            recycle()
                    if claimed:
                        continue
                    deadlines = [
                        time.monotonic() + self.settings.poll_seconds,
                        next_heartbeat,
                    ]
                    if stop_deadline is not None:
                        deadlines.append(stop_deadline)
                        if any(not r.cancelled.is_set() for r in self.active.values()):
                            deadlines.append(
                                stop_deadline - self.settings.cleanup_grace
                            )
                    else:
                        if len(self.active) < self.settings.worker_concurrency:
                            deadlines.append(next_claim)
                        if maintenance_future is None or maintenance_future.done():
                            deadlines.append(next_maintenance)
                    for running in self.active.values():
                        if not running.cancelled.is_set():
                            deadlines.append(
                                min(running.deadline, running.lease_ok_until)
                                - self.settings.cleanup_grace
                            )
                        elif (
                            running.stopped_at is not None
                            and running.process is not None
                            and running.process.poll() is None
                        ):
                            deadlines.append(
                                running.stopped_at + self.settings.cleanup_grace
                            )
                    try:
                        self._wakeups.get(
                            timeout=max(0.0, min(deadlines) - time.monotonic())
                        )
                    except Empty:
                        pass
            except BaseException:
                recycle()
        self.db.close()
        return 78 if self.broken.is_set() else 0


def health() -> bool:
    try:
        state = json.loads(HEALTH.read_text())
        return bool(state["ready"] and time.monotonic() - state["time"] < 60)
    except (OSError, ValueError, KeyError):
        return False
