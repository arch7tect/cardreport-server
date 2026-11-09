import io
import json
import re
import zipfile
from uuid import uuid4

import httpx
import pytest
from playwright.sync_api import Page, Route, expect

pytestmark = pytest.mark.ui


def test_late_version_load_preserves_retention_focus(
    page: Page, api_url: str, template_spec: dict[str, object]
) -> None:
    slug = "ui-focus-" + uuid4().hex
    with httpx.Client(base_url=api_url) as client:
        assert (
            client.post(
                f"/v1/templates/{slug}/versions", json=template_spec
            ).status_code
            == 201
        )
        assert (
            client.patch(
                f"/v1/templates/{slug}", json={"retention_seconds": 7200}
            ).status_code
            == 200
        )
    pending: list[Route] = []
    page.route(
        re.compile(rf"/v1/templates/{slug}/versions(?:\?.*)?$"),
        lambda route: pending.append(route),
    )
    page.goto(f"/ui/#/templates/{slug}")
    retention = page.get_by_label("Retention (seconds)", exact=True)
    expect(retention).to_have_value("7200")
    expect(
        page.get_by_role(
            "button", name="Load more versions", exact=True, include_hidden=True
        )
    ).to_be_disabled()
    retention.focus()
    assert len(pending) == 1
    pending[0].fulfill(json={"items": [], "next": None})
    expect(
        page.get_by_role(
            "button", name="Load more versions", exact=True, include_hidden=True
        )
    ).to_be_enabled()
    expect(retention).to_be_focused()
    retention.press("ControlOrMeta+A")
    retention.press("Backspace")
    expect(retention).to_have_value("")
    page.get_by_role("button", name="Save retention", exact=True).click()
    expect(
        page.get_by_text("Retention saved for future reports.", exact=True)
    ).to_be_visible()
    with httpx.Client(base_url=api_url) as client:
        assert client.get(f"/v1/templates/{slug}").json()["retention_seconds"] is None


def test_policy_and_failed_original(
    page: Page, api_url: str, template_spec: dict[str, object]
) -> None:
    slug = "ui-files-" + uuid4().hex
    with httpx.Client(base_url=api_url) as client:
        assert (
            client.post(
                f"/v1/templates/{slug}/versions", json=template_spec
            ).status_code
            == 201
        )
    page.goto(f"/ui/#/templates/{slug}")
    retention = page.get_by_label("Retention (seconds)", exact=True)
    retention.fill("7200")
    page.get_by_role("button", name="Save retention", exact=True).click()
    expect(
        page.get_by_text("Retention saved for future reports.", exact=True)
    ).to_be_visible()
    page.reload()
    expect(retention).to_have_value("7200")
    page.get_by_role("link", name="New report", exact=True).last.click()
    raw = b"total\r\nnot-an-integer\r\n"
    page.get_by_label("Data files", exact=True).set_input_files(
        {"name": "summary.csv", "mimeType": "text/csv", "buffer": raw}
    )
    page.get_by_role("button", name="Generate report", exact=True).click()
    expect(page.locator(".badge.failed")).to_be_visible(timeout=60000)
    expect(page.get_by_text("7200 seconds", exact=True)).to_be_visible()
    page.get_by_role("button", name="Show input files", exact=True).click()
    area = page.locator("#report-files")
    expect(area.get_by_text("summary.csv", exact=False)).to_be_visible()
    expect(area.get_by_text("failed (invalid_file)", exact=True)).to_be_visible()
    with page.expect_download() as event:
        area.get_by_role("link", name="Download original", exact=True).click()
    assert event.value.path().read_bytes() == raw
    with page.expect_download() as event:
        area.get_by_role("link", name="Download investigation ZIP", exact=True).click()
    with zipfile.ZipFile(io.BytesIO(event.value.path().read_bytes())) as archive:
        assert archive.read("files/1") == raw
        assert json.loads(archive.read("manifest.json"))["template_id"] == slug
    page.get_by_role("button", name="Hide input files", exact=True).click()
    expect(area).to_be_hidden()
    page.goto(f"/ui/#/templates/{slug}")
    retention.fill("")
    page.get_by_role("button", name="Save retention", exact=True).click()
    expect(
        page.get_by_text("Retention saved for future reports.", exact=True)
    ).to_be_visible()
    with httpx.Client(base_url=api_url) as client:
        assert client.get(f"/v1/templates/{slug}").json()["retention_seconds"] is None
