import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from cardreport_server import jobs
from cardreport_server.api import create_app
from cardreport_server.db import Database
from cardreport_server.maintenance import OrphanSweep, maintain
from cardreport_server.settings import Settings
from cardreport_server.storage import Storage
from cardreport_server.templates import register

pytestmark = pytest.mark.integration


def test_snapshot_lifecycle(
    database: Database,
    storage: Storage,
    integration_settings: Settings,
    template_spec: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slug = "data-" + uuid4().hex
    register(database, slug, json.dumps(template_spec).encode(), "application/json")
    app = create_app(integration_settings)
    with TestClient(app) as client:
        assert client.portal is not None
        job = client.post("/v1/reports", params={"template_id": slug}, json={}).json()
        identifier = UUID(job["id"])
        base = job["status_url"]
        for suffix in ["/data", "/datasets", "/dataset?name=x"]:
            assert client.get(base + suffix).status_code == 409
        with database.pool.connection() as conn:
            conn.execute(
                "UPDATE reports SET next_attempt_at=clock_timestamp()+interval '1 day' WHERE state='queued' AND id<>%s",
                (identifier,),
            )
        attempt = jobs.claim(database, integration_settings)
        assert attempt and attempt.report_id == identifier
        path = tmp_path / "snapshot"
        name = "../sales/%/España"
        raw = json.dumps(
            {
                "format": "cardreport.data/1",
                "datasets": {
                    name: {
                        "columns": ["n"],
                        "rows": [{"n": 999999999999000 + i} for i in range(105)],
                    }
                },
            }
        ).encode()
        path.write_bytes(raw)
        key = storage.prefix + f"results/{identifier}/{attempt.token}.data.json"
        result_key = storage.prefix + f"results/{identifier}/{attempt.token}"
        for artifact in (key, result_key):
            storage.put(artifact, path, "application/json")
        meta = {"key": key, "size": len(raw), "hash": hashlib.sha256(raw).hexdigest()}
        assert jobs.finish(
            database,
            attempt,
            result=meta | {"key": result_key},
            data=meta,
            engine_version="test",
            image_id="test",
            service_version="test",
        )
        assert not jobs.finish(
            database,
            attempt,
            result={"key": "wrong"},
            data={"key": "wrong-data"},
            engine_version="test",
            image_id="test",
            service_version="test",
        )
        assert client.get(base).json()["data_available"]
        download = client.get(base + "/data")
        assert (
            download.content == raw and download.headers["cache-control"] == "no-store"
        )
        assert download.headers["etag"] == '"' + str(meta["hash"]) + '"'
        assert client.get(base + "/datasets").json()["items"] == [
            {"name": name, "columns": ["n"], "row_count": 105}
        ]
        page = client.get(
            base + "/dataset", params={"name": name, "offset": 100, "limit": 100}
        )
        assert page.headers["cache-control"] == "no-store"
        assert page.json()["rows"] == [
            [str(999999999999000 + i)] for i in range(100, 105)
        ]
        assert (
            client.get(base + "/dataset", params={"name": name, "offset": 105}).json()[
                "rows"
            ]
            == []
        )
        assert client.get(base + "/dataset?name=missing").status_code == 404
        assert (
            client.get(base + "/dataset?name=" + quote(name) + "&limit=101").status_code
            == 422
        )

        # The view cap fails immediately, releasing the slot after the request.
        async def occupy() -> None:
            app.state.data_view_limiter.acquire_on_behalf_of_nowait("test1")
            app.state.data_view_limiter.acquire_on_behalf_of_nowait("test2")

        client.portal.call(occupy)
        try:
            busy = client.get(base + "/datasets")
            assert busy.status_code == 503 and busy.headers["retry-after"] == "5"
        finally:
            client.portal.call(
                app.state.data_view_limiter.release_on_behalf_of, "test1"
            )
            client.portal.call(
                app.state.data_view_limiter.release_on_behalf_of, "test2"
            )
        orphan = storage.prefix + f"results/{identifier}/loser.data.json"
        storage.put(orphan, path, "application/json")
        original_list = storage.client.list_objects_v2

        def listing(**kwargs: Any) -> Any:
            return {
                "Contents": [
                    {"Key": k, "LastModified": datetime.now(UTC) - timedelta(days=2)}
                    for k in (key, orphan)
                ]
            }

        monkeypatch.setattr(storage.client, "list_objects_v2", listing)
        OrphanSweep().run(database, storage, integration_settings)
        monkeypatch.setattr(storage.client, "list_objects_v2", original_list)
        with pytest.raises(ClientError):
            storage.get(orphan)
        assert client.get(base + "/data").content == raw
        # Input collection does not remove the successful report's data snapshot.
        with database.pool.connection() as conn:
            conn.execute(
                "UPDATE reports SET input_expires_at=clock_timestamp()-interval '1 day' WHERE id=%s",
                (identifier,),
            )
        maintain(database, storage, integration_settings)
        assert client.get(base + "/datasets").status_code == 200
        with database.pool.connection() as conn:
            conn.execute("UPDATE reports SET data_key=NULL WHERE id=%s", (identifier,))
        assert not client.get(base).json()["data_available"]
        assert (
            client.get(base + "/datasets").json()["error"]["code"] == "data_unavailable"
        )
        with database.pool.connection() as conn:
            conn.execute(
                "UPDATE reports SET data_key=%s,result_expires_at=clock_timestamp()-interval '1 day' WHERE id=%s",
                (key, identifier),
            )
        assert client.get(base + "/data").status_code == 410
        assert client.get(base + "/datasets").status_code == 410
        original_delete = storage.delete

        def fail(artifact: str) -> None:
            if artifact == key:
                raise OSError("temporary snapshot delete failure")
            original_delete(artifact)

        monkeypatch.setattr(storage, "delete", fail)
        with pytest.raises(OSError):
            maintain(database, storage, integration_settings)
        with database.pool.connection() as conn:
            row = conn.execute(
                "SELECT result_deleted FROM reports WHERE id=%s", (identifier,)
            ).fetchone()
        assert row and not row["result_deleted"]
        monkeypatch.setattr(storage, "delete", original_delete)
        maintain(database, storage, integration_settings)
        for artifact in (key, result_key):
            with pytest.raises(ClientError):
                storage.get(artifact)
