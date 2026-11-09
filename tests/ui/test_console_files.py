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
    retention = page.get_by_label("Retention (days)", exact=True)
    expect(retention).to_have_value("0.083333")
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
    retention = page.get_by_label("Retention (days)", exact=True)
    retention.fill("0.083333")
    page.get_by_role("button", name="Save retention", exact=True).click()
    expect(
        page.get_by_text("Retention saved for future reports.", exact=True)
    ).to_be_visible()
    page.reload()
    expect(retention).to_have_value("0.083333")
    page.get_by_role("link", name="New report", exact=True).last.click()
    raw = b"total\r\nnot-an-integer\r\n"
    page.get_by_label("Data files", exact=True).set_input_files(
        {"name": "summary.csv", "mimeType": "text/csv", "buffer": raw}
    )
    page.get_by_role("button", name="Generate report", exact=True).click()
    expect(page.locator(".badge.failed")).to_be_visible(timeout=60000)
    expect(page.get_by_text("2 hours", exact=True)).to_be_visible()
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


@pytest.mark.parametrize(
    "seconds,days,label",
    [
        (1, "0.000012", "1 second"),
        (2147483000, "24855.127315", "24855 days 3 hours 3 minutes 20 seconds"),
    ],
)
def test_retention_days_preserve_existing_seconds(
    page: Page,
    api_url: str,
    template_spec: dict[str, object],
    seconds: int,
    days: str,
    label: str,
) -> None:
    slug = "ui-days-" + uuid4().hex
    with httpx.Client(base_url=api_url) as client:
        assert (
            client.post(
                f"/v1/templates/{slug}/versions", json=template_spec
            ).status_code
            == 201
        )
        assert (
            client.patch(
                f"/v1/templates/{slug}", json={"retention_seconds": seconds}
            ).status_code
            == 200
        )
        page.goto(f"/ui/#/templates/{slug}")
        retention = page.get_by_label("Retention (days)", exact=True)
        expect(retention).to_have_value(days)
        expect(
            page.get_by_text(f"Effective retention: {label}.", exact=False)
        ).to_be_visible()
        page.get_by_role("button", name="Save retention", exact=True).click()
        expect(
            page.get_by_text("Retention saved for future reports.", exact=True)
        ).to_be_visible()
        assert (
            client.get(f"/v1/templates/{slug}").json()["retention_seconds"] == seconds
        )


def test_retention_fraction_bounds_and_alignment(
    page: Page, api_url: str, template_spec: dict[str, object]
) -> None:
    slug = "ui-fraction-" + uuid4().hex
    with httpx.Client(base_url=api_url) as client:
        assert (
            client.post(
                f"/v1/templates/{slug}/versions", json=template_spec
            ).status_code
            == 201
        )
        page.goto(f"/ui/#/templates/{slug}")
        retention = page.get_by_label("Retention (days)", exact=True)
        save = page.get_by_role("button", name="Save retention", exact=True)
        expect(retention).to_have_value("")
        box, button_box = retention.bounding_box(), save.bounding_box()
        assert box and button_box
        assert (
            abs((box["y"] + box["height"]) - (button_box["y"] + button_box["height"]))
            <= 1
        )
        hint = retention.get_attribute("aria-describedby")
        assert hint
        expect(page.locator(f"#{hint}")).to_contain_text("Leave empty")
        retention.fill("0.5")
        save.click()
        expect(
            page.get_by_text("Retention saved for future reports.", exact=True)
        ).to_be_visible()
        expect(
            page.get_by_text("Effective retention: 12 hours.", exact=False)
        ).to_be_visible()
        assert client.get(f"/v1/templates/{slug}").json()["retention_seconds"] == 43200
        for bad in ("0", "-1", "0.000001", "24856"):
            retention.fill(bad)
            save.click()
            assert retention.evaluate("element => !element.validity.valid")
            assert (
                client.get(f"/v1/templates/{slug}").json()["retention_seconds"] == 43200
            )
        retention.fill("1")
        save.click()
        expect(
            page.get_by_text("Retention saved for future reports.", exact=True)
        ).to_be_visible()
        assert client.get(f"/v1/templates/{slug}").json()["retention_seconds"] == 86400
