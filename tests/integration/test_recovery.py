import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from cardreport_server import jobs
from cardreport_server.api import create_app
from cardreport_server.db import Database
from cardreport_server.maintenance import maintain
from cardreport_server.settings import Settings
from cardreport_server.storage import Storage
from cardreport_server.templates import register

pytestmark = pytest.mark.integration


def queued(
    database: Database, settings: Settings, template_spec: dict[str, object]
) -> str:
    slug = "recovery-" + uuid4().hex
    register(database, slug, json.dumps(template_spec).encode(), "application/json")
    identifier = uuid4()
    admission = jobs.admit(database, settings, slug, None)
    jobs.enqueue(
        database,
        settings,
        admission,
        identifier,
        settings.s3_prefix + "inputs/" + str(identifier),
        "application/json",
        2,
        "test",
        "pdf",
    )
    with database.pool.connection() as conn:
        conn.execute(
            "UPDATE reports SET next_attempt_at=clock_timestamp()+interval '1 day' WHERE state='queued' AND id<>%s",
            (identifier,),
        )
    return str(identifier)


def test_concurrent_claims_and_reapers(
    database: Database, integration_settings: Settings, template_spec: dict[str, object]
) -> None:
    identifier = queued(database, integration_settings, template_spec)
    with ThreadPoolExecutor(max_workers=6) as pool:
        claimed = list(
            pool.map(lambda _: jobs.claim(database, integration_settings), range(6))
        )
    attempts = [a for a in claimed if a]
    assert len(attempts) == 1 and str(attempts[0].report_id) == identifier
    stale = attempts[0]
    with database.pool.connection() as conn:
        conn.execute(
            "UPDATE reports SET lease_until=clock_timestamp()-interval '1 second',attempt_no=%s WHERE id=%s",
            (integration_settings.max_attempts, identifier),
        )
    with ThreadPoolExecutor(max_workers=6) as pool:
        counts = list(
            pool.map(lambda _: jobs.reap(database, integration_settings), range(6))
        )
    assert sum(counts) >= 1
    assert jobs.status(database, stale.report_id)["state"] == "failed"
    assert not jobs.retry(database, integration_settings, stale)
    assert not jobs.finish(
        database,
        stale,
        result={"key": "wrong"},
        engine_version="x",
        image_id="x",
        service_version="x",
    )


def test_retention_grace_and_delete_retry(
    database: Database,
    storage: Storage,
    integration_settings: Settings,
    template_spec: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identifier = queued(database, integration_settings, template_spec)
    attempt = jobs.claim(database, integration_settings)
    assert attempt is not None
    payload = tmp_path / "payload"
    payload.write_bytes(b"%PDF-test")
    result_key = storage.prefix + "results/" + identifier + "/" + str(attempt.token)
    storage.put(attempt.input_key, payload, "application/json")
    storage.put(result_key, payload, "application/pdf")
    assert jobs.finish(
        database,
        attempt,
        result={"key": result_key, "size": 9, "hash": "test"},
        engine_version="x",
        image_id="x",
        service_version="x",
    )
    with database.pool.connection() as conn:
        conn.execute(
            "UPDATE reports SET result_expires_at=clock_timestamp()-interval '1 second',input_expires_at=clock_timestamp()-interval '1 second' WHERE id=%s",
            (identifier,),
        )
    with TestClient(create_app(integration_settings)) as client:
        assert client.get(f"/v1/reports/{identifier}/content").status_code == 410
    maintain(database, storage, integration_settings)
    assert jobs.status(database, attempt.report_id)["state"] == "expired"
    body = storage.get(result_key)
    assert body.read() == b"%PDF-test"
    body.close()
    with database.pool.connection() as conn:
        conn.execute(
            "UPDATE reports SET result_expires_at=clock_timestamp()-interval '1 day' WHERE id=%s",
            (identifier,),
        )
    original = storage.delete

    def fail(key: str) -> None:
        if key == result_key:
            raise OSError("temporary")
        original(key)

    monkeypatch.setattr(storage, "delete", fail)
    with pytest.raises(OSError):
        maintain(database, storage, integration_settings)
    with database.pool.connection() as conn:
        row = conn.execute(
            "SELECT result_deleted FROM reports WHERE id=%s", (identifier,)
        ).fetchone()
    assert row is not None and not row["result_deleted"]
    monkeypatch.setattr(storage, "delete", original)
    maintain(database, storage, integration_settings)
    with database.pool.connection() as conn:
        row = conn.execute(
            "SELECT result_deleted FROM reports WHERE id=%s", (identifier,)
        ).fetchone()
    assert row is not None and row["result_deleted"]


def test_queue_age_uses_creation(
    database: Database,
    storage: Storage,
    integration_settings: Settings,
    template_spec: dict[str, object],
) -> None:
    identifier = queued(database, integration_settings, template_spec)
    with database.pool.connection() as conn:
        conn.execute(
            "UPDATE reports SET created_at=clock_timestamp()-interval '2 days', next_attempt_at=clock_timestamp()+interval '1 day' WHERE id=%s",
            (identifier,),
        )
    maintain(database, storage, integration_settings)
    with database.pool.connection() as conn:
        row = conn.execute(
            "SELECT state,error FROM reports WHERE id=%s", (identifier,)
        ).fetchone()
    assert (
        row is not None
        and row["state"] == "failed"
        and row["error"]["code"] == "queue_expired"
    )


def test_infrastructure_retry_backoff_cap_and_stale_token(
    database: Database, integration_settings: Settings, template_spec: dict[str, object]
) -> None:
    identifier = queued(database, integration_settings, template_spec)
    old = None
    for number in range(1, integration_settings.max_attempts + 1):
        attempt = jobs.claim(database, integration_settings)
        assert attempt is not None and attempt.attempt_no == number
        if old is not None:
            assert not jobs.finish(
                database,
                old,
                result={"key": "stale"},
                engine_version="x",
                image_id="x",
                service_version="x",
            )
        assert jobs.retry(database, integration_settings, attempt)
        with database.pool.connection() as conn:
            row = conn.execute(
                "SELECT state,next_attempt_at>clock_timestamp() AS delayed FROM reports WHERE id=%s",
                (identifier,),
            ).fetchone()
            assert row is not None
            if number < integration_settings.max_attempts:
                assert row["state"] == "queued" and row["delayed"]
                conn.execute(
                    "UPDATE reports SET next_attempt_at=clock_timestamp() WHERE id=%s",
                    (identifier,),
                )
            else:
                assert row["state"] == "failed"
        old = attempt


@pytest.mark.parametrize("reaper", [False, True])
def test_configured_retry_delay_cap(
    database: Database,
    integration_settings: Settings,
    template_spec: dict[str, object],
    reaper: bool,
) -> None:
    config = integration_settings.model_copy(
        update={"retry_delay": 2, "retry_max_delay": 3}
    )
    identifier = queued(database, config, template_spec)
    with database.pool.connection() as conn:
        conn.execute("UPDATE reports SET attempt_no=1 WHERE id=%s", (identifier,))
    attempt = jobs.claim(database, config)
    assert attempt is not None and attempt.attempt_no == 2
    if reaper:
        with database.pool.connection() as conn:
            conn.execute(
                "UPDATE reports SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",
                (identifier,),
            )
        assert jobs.reap(database, config) >= 1
    else:
        assert jobs.retry(database, config, attempt)
    with database.pool.connection() as conn:
        row = conn.execute(
            "SELECT state,extract(epoch FROM next_attempt_at-clock_timestamp()) AS delay FROM reports WHERE id=%s",
            (identifier,),
        ).fetchone()
    assert row is not None and row["state"] == "queued"
    assert 2 < row["delay"] <= 3


def test_reaper_batch_size(
    database: Database,
    integration_settings: Settings,
    template_spec: dict[str, object],
) -> None:
    attempts = []
    for _ in range(2):
        queued(database, integration_settings, template_spec)
        attempt = jobs.claim(database, integration_settings)
        assert attempt is not None
        attempts.append(attempt)
    with database.pool.connection() as conn:
        conn.execute(
            "UPDATE reports SET lease_until=clock_timestamp()-interval '1 day' WHERE id=ANY(%s)",
            ([a.report_id for a in attempts],),
        )
    config = integration_settings.model_copy(update={"maintenance_batch_size": 1})
    assert jobs.reap(database, config) == 1
    with database.pool.connection() as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM reports WHERE id=ANY(%s) AND state='running'",
            ([a.report_id for a in attempts],),
        ).fetchone()
    assert row is not None and row["n"] == 1
    jobs.reap(database, integration_settings)
