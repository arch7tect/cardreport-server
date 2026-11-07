import hashlib
import os
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from playwright.sync_api import Browser, Page, Route, expect

from cardreport_server.db import Database

pytestmark = pytest.mark.ui
ROOT = Path(__file__).resolve().parents[2]


def wait_geometry(page: Page, expression: str) -> None:
    deadline = time.monotonic() + 3
    while not page.evaluate(expression):
        assert time.monotonic() < deadline, expression
        time.sleep(0.02)


def register_example(api_url: str, name: str = "reference") -> str:
    slug = "ui-run-" + uuid4().hex
    with httpx.Client(base_url=api_url) as client:
        response = client.post(
            f"/v1/templates/{slug}/versions",
            content=(ROOT / f"examples/{name}_template.json").read_bytes(),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201
    return slug


@pytest.mark.parametrize(
    "renderer,extension", [("chromium", "json"), ("weasyprint", "yaml")]
)
def test_upload_preview_and_download(
    page: Page, api_url: str, database: Database, renderer: str, extension: str
) -> None:
    slug = register_example(api_url)
    page.goto(f"/ui/#/new-report?template={slug}&version=1")
    expect(page.get_by_label("Template version", exact=True)).to_have_value("1")
    page.get_by_label("Renderer", exact=True).select_option(renderer)
    page.get_by_label("Output", exact=True).select_option("html")
    source = ROOT / f"examples/reference_data.{extension}"
    page.get_by_label("Dataset file", exact=True).set_input_files(source)
    expect(page.get_by_label("Data format", exact=True)).to_have_value(
        "application/" + ("yaml" if extension == "yaml" else "json")
    )
    page.get_by_role("button", name="Generate report", exact=True).click()
    expect(page.get_by_role("heading", name="Report details")).to_be_visible()
    expect(page.locator(".badge.succeeded")).to_be_visible(timeout=180000)
    identifier = page.url.split("#/reports/")[1].split("?")[0]
    expect(page.get_by_text("Accepted (202):", exact=False)).to_contain_text(identifier)
    assert "accepted=" not in page.url
    with database.pool.connection() as conn:
        row = conn.execute(
            "SELECT input_hash,template_version,renderer FROM reports WHERE id=%s",
            (identifier,),
        ).fetchone()
    assert (
        row is not None
        and row["input_hash"] == hashlib.sha256(source.read_bytes()).hexdigest()
    )
    assert row["template_version"] == 1 and row["renderer"] == renderer
    page.get_by_role("button", name="Preview HTML", exact=True).click()
    frame = page.frame_locator('iframe[title="Report preview"]')
    expect(frame.locator("svg").first).to_be_visible(timeout=30000)
    if renderer == "chromium":
        expect(frame.locator(".barlayer path").first).to_be_visible()
    assert page.locator("iframe").get_attribute("sandbox") == "allow-scripts"
    viewport = page.locator(".preview-viewport")
    expect(page.get_by_label("Preview scale", exact=True)).to_have_value("fit")
    assert viewport.evaluate("e => e.scrollWidth <= e.clientWidth + 1")
    assert page.locator("iframe").evaluate(
        "e => e.getBoundingClientRect().width <= e.parentElement.parentElement.clientWidth + 1"
    )
    page.get_by_label("Preview scale", exact=True).select_option("1")
    assert viewport.evaluate("e => e.scrollWidth > e.clientWidth")
    page.get_by_label("Preview scale", exact=True).select_option("fit")
    page.set_viewport_size({"width": 390, "height": 844})
    # Observe the adjusted frame geometry, not only an assigned transform string.
    expect(page.get_by_label("Preview scale", exact=True)).to_have_value("fit")
    wait_geometry(
        page,
        "document.querySelector('.preview-viewport').scrollWidth <= document.querySelector('.preview-viewport').clientWidth + 1",
    )
    assert frame.locator(".page").first.evaluate(
        "e => e.getBoundingClientRect().width <= innerWidth"
    )
    page.set_viewport_size({"width": 1440, "height": 1000})
    wait_geometry(
        page, "document.querySelector('iframe').getBoundingClientRect().width > 900"
    )

    with page.expect_download() as download:
        page.get_by_role("link", name="Download HTML", exact=True).click()
    payload = Path(download.value.path()).read_bytes()
    assert b"<html" in payload
    # Bring the isolated frame into view so Chromium paints it in full-page captures.
    page.locator(".preview-viewport").scroll_into_view_if_needed()
    # Capture the actual console before teardown for documentation; only bundled data.
    page.screenshot(
        path=str(
            Path(os.environ["CARDREPORT_TEST_ARTIFACTS"]) / f"ui-report-{renderer}.png"
        ),
        full_page=True,
    )
    with httpx.Client(base_url=api_url) as client:
        assert payload == client.get(f"/v1/reports/{identifier}/content").content
    page.get_by_role("link", name="Use these settings", exact=True).click()
    expect(page.get_by_label("Template version", exact=True)).to_have_value("1")
    assert page.get_by_label("Dataset file", exact=True).input_value() == ""


def test_paste_and_pdf_flow(page: Page, api_url: str) -> None:
    from pypdf import PdfReader

    slug = register_example(api_url, "flow")
    page.goto(f"/ui/#/new-report?template={slug}")
    page.get_by_label("Data input", exact=True).select_option("paste")
    page.get_by_label("Dataset source", exact=True).fill(
        (ROOT / "examples/flow_data.json").read_text()
    )
    page.get_by_role("button", name="Generate report", exact=True).click()
    expect(page.locator(".badge.succeeded")).to_be_visible(timeout=180000)
    expect(page.get_by_role("button", name="Preview HTML")).to_be_hidden()
    with page.expect_download() as download:
        page.get_by_role("link", name="Download PDF", exact=True).click()
    pdf = PdfReader(download.value.path())
    assert len(pdf.pages) >= 3
    text = "\n".join(p.extract_text() for p in pdf.pages)
    assert all(text.count(f"ITEM-{i:04d}") == 1 for i in range(1, 151))


def test_render_failure_is_visible(page: Page, api_url: str) -> None:
    slug = register_example(api_url, "flow")
    page.goto(f"/ui/#/new-report?template={slug}")
    page.get_by_label("Renderer", exact=True).select_option("weasyprint")
    page.get_by_label("Dataset file", exact=True).set_input_files(
        ROOT / "examples/flow_data.json"
    )
    page.get_by_role("button", name="Generate report", exact=True).click()
    expect(page.locator(".badge.failed")).to_be_visible(timeout=180000)
    expect(
        page.get_by_text(
            "Renderer does not support this template feature (unsupported_feature)",
            exact=True,
        )
    ).to_be_visible()
    expect(page.get_by_role("link", name="Download PDF")).to_be_hidden()


def test_lost_acceptance_does_not_resubmit(page: Page, api_url: str) -> None:
    slug = register_example(api_url)
    count = 0

    def lose(route: Route) -> None:
        nonlocal count
        if route.request.method == "POST":
            count += 1
            response = route.fetch()
            assert response.status == 202
            route.abort("failed")
        else:
            route.continue_()

    page.route("**/v1/reports?*", lose)
    page.goto(f"/ui/#/new-report?template={slug}")
    page.get_by_label("Dataset file", exact=True).set_input_files(
        ROOT / "examples/reference_data.json"
    )
    page.get_by_role("button", name="Generate report", exact=True).dblclick()
    expect(page.get_by_role("status")).to_contain_text("Acceptance is uncertain")
    assert page.get_by_label("Dataset file", exact=True).input_value()
    assert count == 1
    with httpx.Client(base_url=api_url) as client:
        rows = client.get("/v1/reports", params={"template_id": slug}).json()["items"]
        assert len(rows) == 1


def test_shared_history(browser: Browser, api_url: str) -> None:
    slug = register_example(api_url)
    with httpx.Client(base_url=api_url) as client:
        created = client.post(
            "/v1/reports",
            params={"template_id": slug},
            content=b"{}",
            headers={"Content-Type": "application/json"},
        )
        assert created.status_code == 202
        identifier = created.json()["id"]
    context = browser.new_context(base_url=api_url)
    try:
        second = context.new_page()
        second.goto("/ui/#/reports")
        second.get_by_label("Template ID", exact=True).fill(slug)
        second.get_by_role("button", name="Refresh", exact=True).click()
        expect(
            second.get_by_role("link", name=identifier[:8], exact=True)
        ).to_be_visible()
        second.get_by_role("link", name=identifier[:8], exact=True).click()
        expect(second.get_by_role("heading", name="Report details")).to_be_visible()
        assert second.evaluate("localStorage.length + sessionStorage.length") == 0
    finally:
        context.close()


@pytest.mark.parametrize("size,orientation", [("A4", "portrait"), ("A3", "landscape")])
def test_generated_markup_is_text(
    page: Page, api_url: str, size: str, orientation: str
) -> None:
    import json

    slug = "ui-text-" + uuid4().hex
    marker = '<img src="/canary" onerror="window.escaped=true">'
    spec = {
        "format": "cardreport.template/1",
        "datasets": {
            "summary": {"cardinality": "one", "fields": {"value": {"type": "text"}}}
        },
        "report": {
            "title": marker,
            "page": {"size": size, "orientation": orientation},
            "blocks": [
                {
                    "type": "card",
                    "content": {
                        "type": "kpi",
                        "label": marker,
                        "value": {"bind": {"dataset": "summary", "field": "value"}},
                    },
                }
            ],
        },
    }
    with httpx.Client(base_url=api_url) as client:
        response = client.post(f"/v1/templates/{slug}/versions", json=spec)
        assert response.status_code == 201, response.text
    page.goto(f"/ui/#/new-report?template={slug}")
    page.get_by_label("Output", exact=True).select_option("html")
    page.get_by_label("Data input", exact=True).select_option("paste")
    page.get_by_label("Dataset source", exact=True).fill(
        json.dumps(
            {
                "format": "cardreport.data/1",
                "datasets": {
                    "summary": {"columns": ["value"], "rows": [{"value": marker}]}
                },
            }
        )
    )
    page.get_by_role("button", name="Generate report", exact=True).click()
    expect(page.locator(".badge.succeeded")).to_be_visible(timeout=180000)
    page.get_by_role("button", name="Preview HTML").click()
    frame = page.frame_locator('iframe[title="Report preview"]')
    expect(frame.get_by_text(marker, exact=True).first).to_be_visible()
    expect(frame.locator("img")).to_have_count(0)
    assert page.evaluate("window.escaped") is None
    page.set_viewport_size({"width": 390, "height": 844})
    wait_geometry(
        page,
        "document.querySelector('.preview-viewport').scrollWidth <= document.querySelector('.preview-viewport').clientWidth + 1",
    )

    page.route(
        f"**/v1/templates/{slug}/versions/1",
        lambda route: route.fulfill(
            status=503, json={"error": {"message": "Unavailable"}}
        ),
    )
    page.get_by_role("button", name="Preview HTML").click()
    expect(
        page.get_by_text("Automatic scaling is unavailable.", exact=False)
    ).to_be_visible()
    expect(page.get_by_label("Preview scale", exact=True)).to_be_disabled()
    expect(frame.get_by_text(marker, exact=True).first).to_be_visible()


@pytest.mark.parametrize("renderer", ["chromium", "weasyprint"])
def test_native_pdf_new_tab(browser: Browser, api_url: str, renderer: str) -> None:
    # Full Chromium's new headless mode includes its native PDF viewer; headless-shell does not.
    full = browser.browser_type.launch(channel="chromium")
    context = full.new_context(base_url=api_url)
    context.tracing.start(screenshots=True, snapshots=True)
    downloads: list[str] = []
    main = context.new_page()
    main.on("download", lambda download: downloads.append(download.suggested_filename))
    try:
        slug = register_example(api_url)
        main.goto(f"/ui/#/new-report?template={slug}")
        main.get_by_label("Renderer", exact=True).select_option(renderer)
        main.get_by_label("Dataset file", exact=True).set_input_files(
            ROOT / "examples/reference_data.json"
        )
        main.get_by_role("button", name="Generate report", exact=True).click()
        expect(main.locator(".badge.succeeded")).to_be_visible(timeout=180000)
        link = main.get_by_role("link", name="Open PDF", exact=True)
        expect(link).to_have_attribute("target", "_blank")
        expect(link).to_have_attribute("rel", "noopener noreferrer")
        with context.expect_page() as opened:
            link.click()
        pdf = opened.value
        pdf.on(
            "download", lambda download: downloads.append(download.suggested_filename)
        )
        deadline = time.monotonic() + 15
        while True:
            viewer = next(
                (f for f in pdf.frames if f.url.startswith("chrome-extension://")), None
            )
            if viewer is not None:
                break
            assert time.monotonic() < deadline, "Native PDF viewer did not open"
            pdf.wait_for_timeout(50)
        expect(viewer.locator("viewer-page-selector input")).to_have_value("1")
        assert not downloads
        assert pdf.evaluate("window.opener === null")
        artifact = Path(os.environ["CARDREPORT_TEST_ARTIFACTS"])
        pdf.screenshot(path=str(artifact / f"ui-native-pdf-{renderer}.png"))
    finally:
        context.tracing.stop(
            path=str(
                Path(os.environ["CARDREPORT_TEST_ARTIFACTS"])
                / f"ui-native-pdf-{renderer}.zip"
            )
        )
        context.close()
        full.close()
