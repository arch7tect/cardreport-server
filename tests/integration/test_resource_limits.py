"""Admission budgets survive operator changes and bound retained previews."""

import json
import time
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from cardreport_server import jobs
from cardreport_server.api import create_app
from cardreport_server.db import Database
from cardreport_server.settings import Settings
from cardreport_server.worker import Running, Worker

pytestmark = pytest.mark.integration


def test_raised_policy_render_and_retained_reads(
    database: Database,
    integration_settings: Settings,
    tmp_path: Path,
) -> None:
    settings = integration_settings.model_copy(
        update={
            "data_max_rows": 2500,
            "report_max_table_rows": 2500,
            "template_limit": 2 * 1024 * 1024,
            "temp_root": tmp_path,
        }
    )
    slug = "limits-" + uuid4().hex
    spec = {
        "format": "cardreport.template/1",
        "datasets": {
            "items": {"cardinality": "many", "fields": {"id": {"type": "integer"}}}
        },
        "report": {
            "mode": "flow",
            "blocks": [
                {
                    "type": "table",
                    "dataset": "items",
                    "columns": [{"key": "id", "label": "ID"}],
                }
            ],
        },
    }
    raw = json.dumps(
        {
            "format": "cardreport.data/1",
            "datasets": {
                "items": {"columns": ["id"], "rows": [{"id": i} for i in range(2101)]}
            },
        }
    ).encode()
    with TestClient(create_app(settings)) as client:
        assert (
            client.post(f"/v1/templates/{slug}/versions", json=spec).status_code == 201
        )
        response = client.post(
            "/v1/reports",
            params={"template_id": slug, "output": "html"},
            content=raw,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 202
        base = response.json()["status_url"]
        identifier = UUID(response.json()["id"])
    # Change operator settings before claiming: the accepted policy must win.
    lowered = settings.model_copy(
        update={
            "data_max_rows": 1,
            "report_max_table_rows": 1,
            "input_limit": 100,
            "snapshot_limit": 100,
        }
    )
    with database.pool.connection() as conn:
        conn.execute(
            "UPDATE reports SET next_attempt_at=clock_timestamp()+interval '1 day' WHERE state='queued' AND id<>%s",
            (identifier,),
        )
    attempt = jobs.claim(database, lowered)
    assert attempt and attempt.report_id == identifier
    assert attempt.limits.data.max_rows == 2500
    worker = Worker(lowered)
    worker.db.open()
    try:
        worker.execute(Running(attempt, time.monotonic() + 120, time.monotonic() + 60))
    finally:
        worker.db.close()
    assert jobs.status(database, identifier)["state"] == "succeeded"
    with TestClient(create_app(lowered)) as client:
        assert client.get(base + "/datasets").status_code == 200
        rows = client.get(
            base + "/dataset", params={"name": "items", "offset": 2100}
        ).json()
        assert rows["rows"] == [["2100"]]
        assert client.get(base + "/input").content == raw
    # Preview has an independent current operator budget; downloads remain available.
    with TestClient(create_app(lowered.model_copy(update={"view_limit": 1}))) as client:
        assert client.get(base + "/datasets").status_code == 413
        assert client.get(base + "/files").status_code == 413
        assert client.get(base + "/input").content == raw
        assert client.get(base + "/data").status_code == 200


def test_lowered_template_budget_rejects_before_upload(
    database: Database,
    integration_settings: Settings,
    template_spec: dict[str, object],
) -> None:
    from cardreport_server.templates import register

    slug = "template-budget-" + uuid4().hex
    register(database, slug, json.dumps(template_spec).encode(), "application/json")
    with TestClient(
        create_app(integration_settings.model_copy(update={"template_limit": 1}))
    ) as client:
        response = client.post("/v1/reports", params={"template_id": slug}, json={})
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "template_too_large"


def test_template_exact_canonical_budget_survives_storage(
    database: Database,
    integration_settings: Settings,
    template_spec: dict[str, object],
) -> None:
    from cardreport import ReportTemplate

    raw = ReportTemplate(template_spec).to_json().encode()
    settings = integration_settings.model_copy(update={"template_limit": len(raw)})
    slug = "exact-budget-" + uuid4().hex
    with TestClient(create_app(settings)) as client:
        response = client.post(
            f"/v1/templates/{slug}/versions",
            content=raw,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201
        response = client.post("/v1/reports", params={"template_id": slug}, json={})
        assert response.status_code == 202
    with database.pool.connection() as conn:
        stored = conn.execute(
            "SELECT definition::text AS text, pg_typeof(definition)::text AS type FROM template_versions WHERE template_id=%s",
            (slug,),
        ).fetchone()
    assert stored and stored["type"] == "json"
    assert stored["text"].encode() == raw
    assert (
        ReportTemplate.from_json(stored["text"], max_bytes=len(raw)).to_json().encode()
        == raw
    )
