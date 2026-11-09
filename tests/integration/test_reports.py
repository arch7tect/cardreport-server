import hashlib
import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from cardreport_server import jobs
from cardreport_server.api import create_app
from cardreport_server.db import Database
from cardreport_server.settings import Settings
from cardreport_server.storage import Storage
from cardreport_server.templates import register

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("renderer", [None, "chromium", "weasyprint"])
def test_durable_upload(
    integration_settings: Settings,
    database: Database,
    storage: Storage,
    template_spec: dict[str, object],
    renderer: str | None,
) -> None:
    slug = "data-" + uuid4().hex
    register(database, slug, json.dumps(template_spec).encode(), "application/json")
    data = b'{"format":"cardreport.data/1","datasets":{"summary":[{"total":42}]}}'
    with TestClient(create_app(integration_settings)) as client:
        accepted = client.post(
            "/v1/reports",
            params={"template_id": slug} | ({"renderer": renderer} if renderer else {}),
            content=iter([data[:20], data[20:]]),
            headers={"Content-Type": "application/json"},
        )
        assert accepted.status_code == 202, accepted.text
        body = accepted.json()
        assert body["renderer"] == (renderer or "chromium")
        row = client.get(body["status_url"]).json()
        assert row["state"] == "queued" and row["template_version"] == 1
        assert row["renderer"] == body["renderer"]
        with database.pool.connection() as conn:
            stored = conn.execute(
                "SELECT * FROM reports WHERE id=%s", (body["id"],)
            ).fetchone()
        assert stored is not None
        stream = storage.get(stored["input_key"])
        try:
            assert stream.read() == data
        finally:
            stream.close()
        assert stored["input_hash"] == hashlib.sha256(data).hexdigest()
        assert "input_key" not in row
        assert (
            client.post(
                "/v1/reports",
                params={"template_id": slug, "renderer": "unknown"},
                content=data,
                headers={"Content-Type": "application/json"},
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/v1/reports",
                params={"template_id": slug},
                content="invalid but durably accepted",
                headers={"Content-Type": "application/yaml"},
            ).status_code
            == 202
        )


def test_snapshot_and_fencing(
    integration_settings: Settings, database: Database, template_spec: dict[str, object]
) -> None:
    slug = "snapshot-" + uuid4().hex
    register(database, slug, json.dumps(template_spec).encode(), "application/json")
    admission = jobs.admit(database, integration_settings, slug, None)
    register(database, slug, json.dumps(template_spec).encode(), "application/json")
    with database.pool.connection() as conn:
        conn.execute("UPDATE templates SET archived=true WHERE id=%s", (slug,))
    identifier = uuid4()
    jobs.enqueue(
        database,
        integration_settings,
        admission,
        identifier,
        f"test/no-object/{identifier}",
        "application/json",
        0,
        "none",
        "pdf",
        "weasyprint",
    )
    assert jobs.status(database, identifier)["template_version"] == 1
    with database.pool.connection() as conn:
        # Isolate claims to this test's row; other queued fixtures remain recoverable.
        conn.execute(
            "UPDATE reports SET next_attempt_at=clock_timestamp()+interval '1 day' WHERE state='queued' AND id<>%s",
            (identifier,),
        )
    attempt = jobs.claim(database, integration_settings)
    assert attempt is not None and attempt.report_id == identifier
    assert attempt.renderer == "weasyprint"
    assert jobs.heartbeat(database, integration_settings, [attempt]) == {attempt.token}
    with database.pool.connection() as conn:
        conn.execute(
            "UPDATE reports SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",
            (identifier,),
        )
    assert jobs.heartbeat(database, integration_settings, [attempt]) == set()
    assert not jobs.finish(
        database,
        attempt,
        result={"key": "stale"},
        engine_version="test",
        image_id="test",
        service_version="test",
    )
    assert jobs.reap(database, integration_settings) >= 1
    assert jobs.status(database, identifier)["state"] == "queued"
    with database.pool.connection() as conn:
        conn.execute(
            "UPDATE reports SET next_attempt_at=clock_timestamp() WHERE id=%s",
            (identifier,),
        )
    next_attempt = jobs.claim(database, integration_settings)
    assert next_attempt is not None and next_attempt.report_id == identifier
    assert next_attempt.renderer == "weasyprint" and next_attempt.attempt_no == 2
    assert jobs.retry(database, integration_settings, next_attempt)
    assert jobs.status(database, identifier)["renderer"] == "weasyprint"


def test_failed_enqueue_keeps_orphan_not_job(
    integration_settings: Settings,
    database: Database,
    template_spec: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slug = "orphan-" + uuid4().hex
    register(database, slug, json.dumps(template_spec).encode(), "application/json")

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("sensitive-data-marker")

    monkeypatch.setattr(jobs, "enqueue", fail)
    with TestClient(create_app(integration_settings)) as client:
        response = client.post(
            "/v1/reports",
            params={"template_id": slug},
            content=b"{}",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 500
        assert "sensitive-data-marker" not in response.text
    with database.pool.connection() as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM reports WHERE template_id=%s", (slug,)
        ).fetchone()
    assert row is not None and row["n"] == 0


def test_report_limits(
    integration_settings: Settings, database: Database, template_spec: dict[str, object]
) -> None:
    slug = "limits-" + uuid4().hex
    register(database, slug, json.dumps(template_spec).encode(), "application/json")
    limited = integration_settings.model_copy(update={"input_limit": 10})
    with TestClient(create_app(limited)) as client:
        for payload in (b"x" * 11, iter([b"x" * 6, b"x" * 5])):
            assert (
                client.post(
                    "/v1/reports",
                    params={"template_id": slug},
                    content=payload,
                    headers={"Content-Type": "application/json"},
                ).status_code
                == 413
            )
        assert (
            client.post(
                "/v1/reports",
                params={"template_id": slug},
                content=b"{}",
                headers={"Content-Type": "text/csv"},
            ).status_code
            == 415
        )
        assert client.get("/v1/reports/" + str(UUID(int=0))).status_code == 404
    paused = integration_settings.model_copy(update={"admission_enabled": False})
    with TestClient(create_app(paused)) as client:
        assert (
            client.post(
                "/v1/reports",
                params={"template_id": slug},
                content=b"{}",
                headers={"Content-Type": "application/json"},
            ).status_code
            == 503
        )
        assert client.get("/health/live").status_code == 200


def test_response_lost_after_commit_still_has_job(
    integration_settings: Settings,
    database: Database,
    template_spec: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slug = "committed-" + uuid4().hex
    register(database, slug, json.dumps(template_spec).encode(), "application/json")
    original = jobs.enqueue

    def lose_response(*args: Any, **kwargs: Any) -> None:
        original(*args, **kwargs)
        raise RuntimeError("response path interrupted")

    monkeypatch.setattr(jobs, "enqueue", lose_response)
    with TestClient(create_app(integration_settings)) as client:
        response = client.post(
            "/v1/reports",
            params={"template_id": slug},
            content=b"{}",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 500
    with database.pool.connection() as conn:
        rows = conn.execute(
            "SELECT state FROM reports WHERE template_id=%s", (slug,)
        ).fetchall()
    assert len(rows) == 1 and rows[0]["state"] == "queued"


def test_multipart_is_durable_without_api_parsing(
    integration_settings: Settings,
    database: Database,
    storage: Storage,
    template_spec: dict[str, object],
) -> None:
    slug = "csv-" + uuid4().hex
    register(database, slug, json.dumps(template_spec).encode(), "application/json")
    with TestClient(create_app(integration_settings)) as client:
        request = client.build_request(
            "POST",
            "/v1/reports",
            params={"template_id": slug},
            files=[("files", ("summary.csv", b"total\n42\n"))],
        )
        raw = request.read()
        response = client.send(request)
        assert response.status_code == 202, response.text
        with database.pool.connection() as conn:
            row = conn.execute(
                "SELECT input_key,input_type,input_size,input_hash FROM reports WHERE id=%s",
                (response.json()["id"],),
            ).fetchone()
        assert row is not None
        assert "boundary=" in row["input_type"]
        assert row["input_size"] == len(raw)
        assert row["input_hash"] == hashlib.sha256(raw).hexdigest()
        stream = storage.get(row["input_key"])
        try:
            assert stream.read() == raw
        finally:
            stream.close()
        bad = client.post(
            "/v1/reports",
            params={"template_id": slug},
            content=b"broken",
            headers={"Content-Type": "multipart/form-data; boundary=test"},
        )
        assert bad.status_code == 202  # Body validation belongs to the child.
        assert (
            client.post(
                "/v1/reports",
                params={"template_id": slug},
                content=b"",
                headers={"Content-Type": "multipart/form-data"},
            ).status_code
            == 400
        )
