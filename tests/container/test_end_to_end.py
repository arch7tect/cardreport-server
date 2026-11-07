import hashlib
import io
import os
import time
from importlib.metadata import version
from pathlib import Path
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
            if name == "flow":
                assert len(pdf.pages) >= 3
                for i in range(1, 151):
                    assert text.count(f"ITEM-{i:04d}") == 1
        else:
            assert "<html" in content.text.lower()
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
