from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from cardreport_server import maintenance
from cardreport_server.db import Database
from cardreport_server.maintenance import CLEANUP_LOCK, OrphanSweep, cleanup
from cardreport_server.settings import Settings
from cardreport_server.storage import Storage

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("held_stage", ["retention", "orphans"])
def test_cleanup_skips_busy_session_and_works_with_one_pool_slot(
    integration_settings: Settings,
    storage: Storage,
    monkeypatch: pytest.MonkeyPatch,
    held_stage: str,
) -> None:
    config = integration_settings.model_copy(update={"db_pool_size": 1})
    owner, contender = Database(config), Database(config)
    owner.open()
    contender.open()
    entered, release = Event(), Event()
    calls: list[str] = []

    def stage(name: str, db: Database) -> None:
        with db.pool.connection() as conn:
            assert conn.execute("SELECT 1 AS available").fetchone() == {"available": 1}
        calls.append(name)
        if name == held_stage and not release.is_set():
            entered.set()
            assert release.wait(10), "Test did not release cleanup"

    def retention(db: Database, store: Storage, settings: Settings) -> None:
        stage("retention", db)

    class Sweep(OrphanSweep):
        def run(self, db: Database, store: Storage, settings: Settings) -> None:
            stage("orphans", db)

    monkeypatch.setattr(maintenance, "maintain", retention)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(cleanup, owner, storage, config, Sweep())
            try:
                assert entered.wait(5)
                before = list(calls)
                second = executor.submit(cleanup, contender, storage, config, Sweep())
                assert second.result(timeout=3) is False
                assert calls == before  # Neither retention nor the orphan scan ran.
            finally:
                release.set()
            assert first.result(timeout=5) is True
        assert calls == ["retention", "orphans"]
        assert cleanup(contender, storage, config, Sweep()) is True
        assert calls == ["retention", "orphans", "retention", "orphans"]
    finally:
        release.set()
        owner.close()
        contender.close()


@pytest.mark.parametrize("failed_stage", ["retention", "orphans"])
def test_cleanup_releases_session_after_failure(
    database: Database,
    integration_settings: Settings,
    storage: Storage,
    monkeypatch: pytest.MonkeyPatch,
    failed_stage: str,
) -> None:
    fail = True
    calls: list[str] = []

    def stage(name: str) -> None:
        calls.append(name)
        if fail and name == failed_stage:
            raise RuntimeError("Injected storage failure")

    def retention(db: Database, store: Storage, settings: Settings) -> None:
        stage("retention")

    class Sweep(OrphanSweep):
        def run(self, db: Database, store: Storage, settings: Settings) -> None:
            stage("orphans")

    monkeypatch.setattr(maintenance, "maintain", retention)
    with pytest.raises(RuntimeError, match="Injected storage failure"):
        cleanup(database, storage, integration_settings, Sweep())
    assert calls == (
        ["retention"] if failed_stage == "retention" else ["retention", "orphans"]
    )
    fail = False
    assert cleanup(database, storage, integration_settings, Sweep()) is True
    assert calls[-2:] == ["retention", "orphans"]


def test_cleanup_acquires_after_owner_connection_terminated(
    database: Database,
    integration_settings: Settings,
    storage: Storage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def retention(db: Database, store: Storage, settings: Settings) -> None:
        calls.append("retention")

    class Sweep(OrphanSweep):
        def run(self, db: Database, store: Storage, settings: Settings) -> None:
            calls.append("orphans")

    monkeypatch.setattr(maintenance, "maintain", retention)
    # Use a real backend termination, not an explicit unlock or mocked connection.
    owner = database.dedicated_connection()
    try:
        assert owner.autocommit
        assert owner.execute(
            "SELECT pg_try_advisory_lock(%s, %s) AS acquired", CLEANUP_LOCK
        ).fetchone() == {"acquired": True}
        assert cleanup(database, storage, integration_settings, Sweep()) is False
        assert calls == []
        with database.pool.connection() as conn:
            assert conn.execute(
                "SELECT pg_terminate_backend(%s, 5000) AS terminated",
                (owner.info.backend_pid,),
            ).fetchone() == {"terminated": True}
        assert cleanup(database, storage, integration_settings, Sweep()) is True
        assert calls == ["retention", "orphans"]
    finally:
        owner.close()
