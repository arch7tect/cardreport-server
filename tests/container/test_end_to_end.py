import hashlib
import io
import os
import time
from importlib.metadata import version
from pathlib import Path
from typing import IO
from uuid import uuid4

import httpx
import pytest
from pypdf import PdfReader

from cardreport_server.settings import Settings

pytestmark = pytest.mark.container
ROOT = Path(__file__).resolve().parents[2]


def wait(client: httpx.Client, url: str) -> dict[str, object]:
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        response = client.get(url)
        response.raise_for_status()
        status = response.json()
        if status["state"] in {"succeeded", "failed", "expired"}:
            return dict(status)
        time.sleep(0.2)
    raise TimeoutError("Job did not finish")


@pytest.mark.parametrize(
    "name,extension,output,renderer",
    [
        ("reference", "json", "pdf", "chromium"),
        ("reference", "yaml", "html", "chromium"),
        ("flow", "json", "pdf", "chromium"),
        ("reference", "json", "pdf", "weasyprint"),
        ("reference", "yaml", "html", "weasyprint"),
        ("daily", "json", "pdf", "chromium"),
        ("daily", "yaml", "pdf", "weasyprint"),
        ("daily", "yaml", "html", "chromium"),
    ],
)
def test_complete_report(
    integration_settings: Settings,
    name: str,
    extension: str,
    output: str,
    renderer: str,
) -> None:
    slug = "e2e-" + uuid4().hex
    media = "application/json" if extension == "json" else "application/yaml"
    with httpx.Client(
        base_url="http://127.0.0.1:" + os.environ["API_PORT"], timeout=150
    ) as client:
        registered = client.post(
            f"/v1/templates/{slug}/versions",
            content=(ROOT / f"examples/{name}_template.{extension}").read_bytes(),
            headers={"Content-Type": media},
        )
        assert registered.status_code == 201, registered.text
        data = (ROOT / f"examples/{name}_data.{extension}").read_bytes()
        response = client.post(
            "/v1/reports",
            params={"template_id": slug, "output": output, "renderer": renderer},
            content=(data[i : i + 1024] for i in range(0, len(data), 1024)),
            headers={"Content-Type": media},
        )
        assert response.status_code == 202, response.text
        job = response.json()
        status = wait(client, job["status_url"])
        assert status["state"] == "succeeded", status
        assert job["renderer"] == status["renderer"] == renderer
        content = client.get(job["content_url"])
        assert content.status_code == 200
        assert len(content.content) == int(content.headers["content-length"])
        assert (
            content.headers["etag"].strip('"')
            == hashlib.sha256(content.content).hexdigest()
        )
        assert "attachment" in content.headers["content-disposition"]
        assert status["engine_version"] == version("cardreport")
        destination = ROOT / "output" / f"{name}-{renderer}.{output}"
        destination.parent.mkdir(exist_ok=True)
        destination.write_bytes(content.content)
        if output == "pdf":
            pdf = PdfReader(io.BytesIO(content.content))
            text = "\n".join(page.extract_text() for page in pdf.pages)
            assert text.strip()
            if name == "daily":
                assert "Daily report for 14.11.2026" in text
                assert "Month: November 2026" in text
                assert "97.6%" in text
                assert "Updated 15.11.2026 00:30 +02:00" in text
            if name == "flow":
                assert len(pdf.pages) >= 3
                for i in range(1, 151):
                    assert text.count(f"ITEM-{i:04d}") == 1
        else:
            assert "<html" in content.text.lower()
            if name == "daily":
                assert "Daily report for 14.11.2026" in content.text
                assert "{{ datasets." not in content.text
                assert "Updated 15.11.2026 00:30 +02:00" in content.text
            if renderer == "weasyprint":
                assert "<svg" in content.text and "<script" not in content.text


def test_invalid_data_terminal(integration_settings: Settings) -> None:
    slug = "bad-" + uuid4().hex
    with httpx.Client(
        base_url="http://127.0.0.1:" + os.environ["API_PORT"], timeout=20
    ) as client:
        assert (
            client.post(
                f"/v1/templates/{slug}/versions",
                content=(ROOT / "examples/reference_template.json").read_bytes(),
                headers={"Content-Type": "application/json"},
            ).status_code
            == 201
        )
        response = client.post(
            "/v1/reports",
            params={"template_id": slug},
            content=b'{"private-marker":',
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 202
        job = response.json()
        status = wait(client, job["status_url"])
        assert status["state"] == "failed"
        assert status["attempts"] == 1
        assert status["error"] == {
            "code": "invalid_data",
            "stage": "bind",
            "message": "Datasets do not satisfy the template or data limits",
            "retryable": False,
        }
        assert client.get(job["content_url"]).status_code == 409


@pytest.mark.parametrize("output", ["pdf", "html"])
def test_weasyprint_flow_is_terminal(
    integration_settings: Settings, output: str
) -> None:
    slug = "flow-" + uuid4().hex
    with httpx.Client(
        base_url="http://127.0.0.1:" + os.environ["API_PORT"], timeout=20
    ) as client:
        response = client.post(
            f"/v1/templates/{slug}/versions",
            content=(ROOT / "examples/flow_template.json").read_bytes(),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201
        response = client.post(
            "/v1/reports",
            params={"template_id": slug, "output": output, "renderer": "weasyprint"},
            content=(ROOT / "examples/flow_data.json").read_bytes(),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 202
        job = response.json()
        status = wait(client, job["status_url"])
        assert status["state"] == "failed" and status["attempts"] == 1
        assert status["renderer"] == "weasyprint"
        assert status["error"] == {
            "code": "unsupported_feature",
            "stage": "render",
            "message": "Renderer does not support this template feature",
            "retryable": False,
        }
        assert client.get(job["content_url"]).status_code == 409


@pytest.mark.parametrize("renderer", ["chromium", "weasyprint"])
@pytest.mark.parametrize("mixed", [False, True])
def test_csv_report(integration_settings: Settings, renderer: str, mixed: bool) -> None:
    import json
    from contextlib import ExitStack

    slug = "csv-e2e-" + uuid4().hex
    with (
        httpx.Client(
            base_url="http://127.0.0.1:" + os.environ["API_PORT"], timeout=150
        ) as client,
        ExitStack() as files,
    ):
        registered = client.post(
            f"/v1/templates/{slug}/versions",
            content=(ROOT / "examples/reference_template.json").read_bytes(),
            headers={"Content-Type": "application/json"},
        )
        assert registered.status_code == 201
        parts: list[tuple[str, tuple[str, IO[bytes] | str, str]]] = []
        for path in sorted((ROOT / "examples/reference_csv").glob("*.csv")):
            if not mixed or path.stem == "summary":
                parts.append(
                    (
                        "files",
                        (path.name, files.enter_context(path.open("rb")), "text/csv"),
                    )
                )
        if mixed:
            data = json.loads((ROOT / "examples/reference_data.json").read_text())
            del data["datasets"]["summary"]
            parts.append(
                ("files", ("other.yaml", json.dumps(data), "application/octet-stream"))
            )
        response = client.post(
            "/v1/reports",
            params={"template_id": slug, "template_version": 1, "renderer": renderer},
            files=parts,
        )
        assert response.status_code == 202, response.text
        job = response.json()
        status = wait(client, job["status_url"])
        assert status["state"] == "succeeded", status
        catalog = client.get(job["status_url"] + "/files").json()
        assert all(f["status"] == "parsed" and f["datasets"] for f in catalog["files"])
        assert len(catalog["files"]) == len(parts)
        pdf = PdfReader(io.BytesIO(client.get(job["content_url"]).content))
        text = "\n".join(page.extract_text() for page in pdf.pages)
        assert "21" in text and "Call attempted" in text
        # Malformed CSV and multipart are terminal validation errors, not retries.
        invalid_csv = httpx.Request(
            "POST",
            "http://test",
            files=[("files", ("summary.csv", b"clients\nprivate-marker\n"))],
        )
        for content, content_type in (
            (b"broken", "multipart/form-data; boundary=test"),
            (invalid_csv.read(), invalid_csv.headers["content-type"]),
        ):
            bad = client.post(
                "/v1/reports",
                params={"template_id": slug},
                content=content,
                headers={"Content-Type": content_type},
            ).json()
            failed = wait(client, bad["status_url"])
            assert failed["state"] == "failed" and failed["attempts"] == 1
            assert failed["error"]["code"] == "invalid_data"  # type: ignore[index]
            assert client.get(bad["status_url"] + "/input").content == content
            files = client.get(bad["status_url"] + "/files").json()
            if content == b"broken":
                assert files["structure"] == "invalid" and files["files"] == []
            else:
                assert files["files"][0]["status"] == "failed"
                assert files["files"][0]["error"] == "invalid_file"
                assert (
                    client.get(bad["status_url"] + "/files/1/content").content
                    == b"clients\nprivate-marker\n"
                )


@pytest.mark.parametrize("renderer", ["chromium", "weasyprint"])
def test_natural_table_card(integration_settings: Settings, renderer: str) -> None:
    """A natural table card must fit without a fixed-height wrapper."""
    slug = "natural-card-" + uuid4().hex
    template = {
        "format": "cardreport.template/1",
        "datasets": {
            "items": {"cardinality": "many", "fields": {"name": {"type": "text"}}}
        },
        "report": {
            "title": "Natural card regression",
            "mode": "dashboard",
            "blocks": [
                {
                    "type": "row",
                    "height_mm": 50,
                    "children": [
                        {
                            "type": "card",
                            "content": {"type": "text", "text": "Overview"},
                        }
                    ],
                },
                {
                    "type": "card",
                    "title": "Items",
                    "content": {
                        "type": "table",
                        "dataset": "items",
                        "columns": [{"key": "name", "label": "Item"}],
                    },
                },
                {"type": "text", "text": "Following block"},
            ],
        },
    }
    labels = [f"ITEM-{i:04d}" for i in range(1, 10)]
    data = {
        "format": "cardreport.data/1",
        "datasets": {
            "items": {
                "columns": ["name"],
                "rows": [{"name": label} for label in labels],
            }
        },
    }
    with httpx.Client(
        base_url="http://127.0.0.1:" + os.environ["API_PORT"], timeout=150
    ) as client:
        registered = client.post(f"/v1/templates/{slug}/versions", json=template)
        assert registered.status_code == 201, registered.text
        submitted = client.post(
            "/v1/reports",
            params={"template_id": slug, "renderer": renderer, "output": "pdf"},
            json=data,
        )
        assert submitted.status_code == 202, submitted.text
        job = submitted.json()
        status = wait(client, job["status_url"])
        assert status["state"] == "succeeded", status
        assert status["engine_version"] == version("cardreport")
        content = client.get(job["content_url"])
        assert content.status_code == 200, content.text
        pdf = PdfReader(io.BytesIO(content.content))
        assert len(pdf.pages) == 1
        text = pdf.pages[0].extract_text()
        for label in labels:
            assert text.count(label) == 1
        assert "Following block" in text
