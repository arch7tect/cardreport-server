import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import yaml
from playwright.sync_api import Dialog, Page, expect

pytestmark = pytest.mark.ui
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("kind", ["json", "yaml"])
def test_template_lifecycle(page: Page, api_url: str, kind: str) -> None:
    slug = "ui-" + uuid4().hex
    source = (ROOT / "examples/reference_template.json").read_text()
    page.goto("/ui/#/create-template")
    page.get_by_label("Template ID", exact=True).fill(slug)
    page.get_by_label("Source format").select_option("application/" + kind)
    text = source if kind == "json" else yaml.safe_dump(json.loads(source))
    page.get_by_label("Template source", exact=True).fill("invalid: [")
    page.get_by_role("button", name="Save new version").click()
    expect(page.get_by_role("status")).to_contain_text("invalid_template")
    expect(page.get_by_label("Template source", exact=True)).to_have_value("invalid: [")
    page.get_by_label("Import template file", exact=True).set_input_files(
        {
            "name": f"template.{kind}",
            "mimeType": "application/" + kind,
            "buffer": text.encode(),
        }
    )
    expect(page.get_by_label("Template source", exact=True)).to_have_value(text)
    page.get_by_role("button", name="Save new version").click()
    expect(page.get_by_role("heading", name=slug, exact=True)).to_be_visible()
    expect(page.get_by_label("Version", exact=True)).to_have_value("1")
    page.get_by_role("link", name="Create new version", exact=True).click()
    expect(page.get_by_label("Template source", exact=True)).not_to_have_value("")
    # Another caller appends first: UI must use the server's actual version.
    with httpx.Client(base_url=api_url) as client:
        response = client.post(
            f"/v1/templates/{slug}/versions",
            content=source,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201
    page.get_by_role("button", name="Save new version").click()
    expect(page.get_by_label("Version", exact=True)).to_have_value("3")
    with page.expect_download() as download:
        page.get_by_role("button", name="Download JSON", exact=True).click()
    assert (
        json.loads(Path(download.value.path()).read_text())["format"]
        == "cardreport.template/1"
    )
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Archive template", exact=True).click()
    expect(page.get_by_role("button", name="Restore template")).to_be_visible()
    expect(
        page.get_by_role("link", name="Create new version", exact=True)
    ).to_have_count(0)
    page.get_by_role("button", name="Restore template").click()
    expect(
        page.get_by_role("link", name="Create new version", exact=True)
    ).to_be_visible()


def test_unsaved_source_and_safe_text(page: Page) -> None:
    page.goto("/ui/#/create-template")
    source = page.get_by_label("Template source", exact=True)
    source.fill("<script>window.bad = true</script>")
    decisions = iter([False, True])

    def decide(dialog: Dialog) -> None:
        if next(decisions):
            dialog.accept()
        else:
            dialog.dismiss()

    page.on("dialog", decide)
    with page.expect_event("dialog"):
        page.get_by_role("link", name="Reports", exact=True).click()
    expect(source).to_have_value("<script>window.bad = true</script>")
    assert page.evaluate("window.bad") is None
    with page.expect_event("dialog"):
        page.get_by_role("link", name="Templates", exact=True).first.click()
    expect(page.get_by_role("heading", name="Templates", exact=True)).to_be_visible()


def test_offline_assets_and_narrow_layout(page: Page, api_url: str) -> None:
    from playwright.sync_api import Route

    external: list[str] = []

    def restrict(route: Route) -> None:
        if route.request.url.startswith(api_url):
            route.continue_()
        else:
            external.append(route.request.url)
            route.abort()

    page.route("**/*", restrict)
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto("/ui/#/create-template")
    expect(page.get_by_role("button", name="Save new version")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.get_by_label("Template ID", exact=True).focus()
    page.keyboard.press("Tab")
    expect(page.get_by_label("Source format")).to_be_focused()
    assert not external
