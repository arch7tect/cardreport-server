import hashlib
import io
import json
import zipfile
from uuid import UUID, uuid4

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from cardreport_server import jobs
from cardreport_server.api import create_app
from cardreport_server.db import Database
from cardreport_server.maintenance import maintain
from cardreport_server.settings import Settings
from cardreport_server.storage import Storage
from cardreport_server.templates import register

pytestmark = pytest.mark.integration


def test_original_files_failed_report_and_expiry(
    database: Database,
    storage: Storage,
    integration_settings: Settings,
    template_spec: dict[str, object],
) -> None:
    slug = "files-" + uuid4().hex
    register(database, slug, json.dumps(template_spec).encode(), "application/json")
    app = create_app(integration_settings)
    with TestClient(app) as client:
        parts = [
            ("files", ("same.csv", b"v\r\ninvalid\r\n")),
            ("files", ("same.csv", b"v\n2\n")),
            ("csv_null", (None, "NULL")),
        ]
        response = client.post("/v1/reports", params={"template_id": slug}, files=parts)
        assert response.status_code == 202
        base = response.json()["status_url"]
        report_id = UUID(response.json()["id"])
        catalog = client.get(base + "/files").json()
        assert [f["name"] for f in catalog["files"]] == ["same.csv", "same.csv"]
        assert [f["status"] for f in catalog["files"]] == ["unknown", "unknown"]
        assert catalog["fields"] == [["csv_null", "NULL"]]
        for n, part in enumerate(parts[:2], 1):
            content = client.get(base + f"/files/{n}/content")
            assert content.content == part[1][1]
            assert content.headers["content-type"] == "application/octet-stream"
            assert "attachment" in content.headers["content-disposition"]
            assert content.headers["cache-control"] == "no-store"
            assert (
                catalog["files"][n - 1]["sha256"]
                == hashlib.sha256(content.content).hexdigest()
            )
        assert client.get(base + "/files/3/content").status_code == 404
        with database.pool.connection() as conn:
            conn.execute(
                "UPDATE reports SET next_attempt_at=clock_timestamp()+interval '1 day' WHERE state='queued' AND id<>%s",
                (report_id,),
            )
        attempt = jobs.claim(database, integration_settings)
        assert attempt and attempt.report_id == report_id
        diagnostics = [
            {"id": 1, "status": "failed", "datasets": [], "error": "invalid_file"},
            {"id": 2, "status": "skipped", "datasets": [], "error": None},
        ]
        assert jobs.finish(
            database,
            attempt,
            error={"code": "invalid_data"},
            files=diagnostics,
            engine_version="test",
            service_version="test",
            image_id="test",
        )
        assert not jobs.finish(
            database,
            attempt,
            error={"code": "wrong"},
            files=[],
            engine_version="test",
            service_version="test",
            image_id="test",
        )
        assert client.get(base + "/files").json()["files"][0]["status"] == "failed"
        raw = client.get(base + "/input").content
        archive = client.get(base + "/inputs.zip")
        with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
            assert bundle.read("input.raw") == raw
            assert bundle.read("files/1") == parts[0][1][1]
            assert bundle.read("files/2") == parts[1][1][1]
            assert json.loads(bundle.read("template.json")) == template_spec
            assert (
                json.loads(bundle.read("manifest.json"))["error"]["code"]
                == "invalid_data"
            )
        with database.pool.connection() as conn:
            conn.execute(
                "UPDATE reports SET input_expires_at=clock_timestamp()-interval '1 second' WHERE id=%s",
                (report_id,),
            )
        for suffix in ["/input", "/files", "/files/1/content", "/inputs.zip"]:
            assert client.get(base + suffix).status_code == 410
        maintain(database, storage, integration_settings)
        # An already-started download still has its full grace period.
        body = storage.get(attempt.input_key)
        assert body.read() == raw
        body.close()
        with database.pool.connection() as conn:
            conn.execute(
                "UPDATE reports SET input_expires_at=clock_timestamp()-interval '1 day' WHERE id=%s",
                (report_id,),
            )
        maintain(database, storage, integration_settings)
        with pytest.raises(ClientError):
            storage.get(attempt.input_key)


def test_retention_is_admission_snapshot(
    database: Database, integration_settings: Settings, template_spec: dict[str, object]
) -> None:
    slug = "policy-" + uuid4().hex
    register(database, slug, json.dumps(template_spec).encode(), "application/json")
    with TestClient(create_app(integration_settings)) as client:
        url = "/v1/templates/" + slug
        assert (
            client.get(url).json()["effective_retention_seconds"]
            == integration_settings.result_retention
        )
        for body in [
            {},
            {"archived": None},
            {"retention_seconds": 0},
            {"retention_seconds": True},
            {"retention_seconds": 2147483001},
        ]:
            assert client.patch(url, json=body).status_code == 422
        assert client.patch(url, json={"retention_seconds": 900000}).status_code == 200
        admission = jobs.admit(database, integration_settings, slug, None)
        assert admission.retention == 900000
        assert (
            admission.metadata_retention
            > 900000 + integration_settings.download_timeout
        )
        assert client.patch(url, json={"retention_seconds": 30}).status_code == 200
        report_id = uuid4()
        jobs.enqueue(
            database,
            integration_settings,
            admission,
            report_id,
            "test-policy/" + str(report_id),
            "application/json",
            2,
            "hash",
            "html",
        )
        with database.pool.connection() as conn:
            row = conn.execute(
                "SELECT input_retention,result_retention,metadata_retention FROM reports WHERE id=%s",
                (report_id,),
            ).fetchone()
        assert row and row["input_retention"] == row["result_retention"] == 900000
        assert (
            client.patch(url, json={"archived": True}).json()["retention_seconds"] == 30
        )
        assert client.patch(url, json={"retention_seconds": None}).json()["archived"]
        assert (
            client.get(url).json()["effective_retention_seconds"]
            == integration_settings.result_retention
        )


def test_malformed_original_and_view_limits(
    database: Database,
    integration_settings: Settings,
    template_spec: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slug = "malformed-" + uuid4().hex
    register(database, slug, json.dumps(template_spec).encode(), "application/json")
    app = create_app(integration_settings)
    with TestClient(app) as client:
        job = client.post(
            "/v1/reports",
            params={"template_id": slug},
            content=b"broken body",
            headers={"Content-Type": "multipart/form-data; boundary=abc"},
        ).json()
        base = job["status_url"]
        catalog = client.get(base + "/files").json()
        assert catalog["structure"] == "invalid" and catalog["files"] == []
        assert client.get(base + "/input").content == b"broken body"
        assert client.get(base + "/files/1/content").status_code == 404
        assert client.portal

        async def occupy() -> None:
            for i in range(integration_settings.data_view_slots):
                app.state.data_view_limiter.acquire_on_behalf_of_nowait(i)

        client.portal.call(occupy)
        try:
            assert client.get(base + "/files").status_code == 503
        finally:
            for i in range(integration_settings.data_view_slots):
                client.portal.call(app.state.data_view_limiter.release_on_behalf_of, i)
        assert client.get(base + "/files").status_code == 200
        with database.pool.connection() as conn:
            conn.execute(
                "UPDATE reports SET input_hash=%s WHERE id=%s",
                ("wrong", UUID(job["id"])),
            )
        assert client.get(base + "/input").status_code == 503


def test_empty_input_remains_downloadable(
    database: Database, integration_settings: Settings, template_spec: dict[str, object]
) -> None:
    slug = "empty-" + uuid4().hex
    register(database, slug, json.dumps(template_spec).encode(), "application/json")
    with TestClient(create_app(integration_settings)) as client:
        accepted = client.post(
            "/v1/reports",
            params={"template_id": slug},
            content=b"",
            headers={"Content-Type": "application/json"},
        )
        assert accepted.status_code == 202
        base = accepted.json()["status_url"]
        assert client.get(base + "/input").content == b""
        response = client.get(base + "/files/1/content")
        assert response.status_code == 200 and response.content == b""
        assert client.get(base + "/files").json()["files"][0]["size"] == 0
