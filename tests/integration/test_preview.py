import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from cardreport_server.api import create_app
from cardreport_server.db import Database
from cardreport_server.settings import Settings
from cardreport_server.storage import Storage
from cardreport_server.templates import register

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("output", ["html", "pdf"])
def test_inline_contract(
    integration_settings: Settings,
    database: Database,
    storage: Storage,
    template_spec: dict[str, object],
    tmp_path: Path,
    output: str,
) -> None:
    slug = "preview-" + uuid4().hex
    register(database, slug, json.dumps(template_spec).encode(), "application/json")
    with TestClient(create_app(integration_settings)) as client:
        response = client.post(
            "/v1/reports",
            params={"template_id": slug, "output": output},
            content=b"{}",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 202
        job = response.json()
        url = job["content_url"]
        assert client.get(url + "?disposition=inline").status_code == 409
        assert client.get(url + "?disposition=other").status_code == 422
        payload = (
            b"<html><body>Result</body></html>" if output == "html" else b"%PDF-test"
        )
        path = tmp_path / "result"
        path.write_bytes(payload)
        key = storage.prefix + "results/" + job["id"]
        storage.put(key, path, "text/html" if output == "html" else "application/pdf")
        with database.pool.connection() as conn:
            conn.execute(
                "UPDATE reports SET state='succeeded',terminal_state='succeeded',result_key=%s,result_size=%s,result_hash=%s,result_expires_at=clock_timestamp()+interval '1 hour' WHERE id=%s",
                (key, len(payload), hashlib.sha256(payload).hexdigest(), job["id"]),
            )
        attachment = client.get(url)
        assert attachment.status_code == 200 and attachment.content == payload
        assert attachment.headers["content-disposition"].startswith("attachment;")
        assert attachment.headers["content-security-policy"].startswith("sandbox;")
        inline = client.get(url + "?disposition=inline")
        assert inline.status_code == 200 and inline.content == attachment.content
        assert inline.headers["etag"] == attachment.headers["etag"]
        assert inline.headers["content-disposition"].startswith("inline;")
        assert inline.headers["cache-control"] == "no-store"
        assert inline.headers["x-content-type-options"] == "nosniff"
        assert "accept-ranges" not in inline.headers
        policy = inline.headers["content-security-policy"]
        if output == "html":
            assert "sandbox allow-scripts;" in policy and "connect-src 'none'" in policy
            assert "allow-same-origin" not in policy
        else:
            assert inline.headers["content-type"] == "application/pdf"
            assert "sandbox" not in policy and "frame-ancestors 'none'" in policy
        with database.pool.connection() as conn:
            conn.execute(
                "UPDATE reports SET result_expires_at=clock_timestamp()-interval '1 second' WHERE id=%s",
                (job["id"],),
            )
        assert client.get(url + "?disposition=inline").status_code == 410
        assert (
            client.get(f"/v1/reports/{uuid4()}/content?disposition=inline").status_code
            == 404
        )
