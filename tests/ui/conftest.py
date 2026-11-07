import os
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Browser, Page, sync_playwright

from cardreport_server.settings import Settings


@pytest.fixture(scope="session")
def api_url(integration_settings: Settings) -> str:
    return "http://127.0.0.1:" + os.environ["API_PORT"]


@pytest.fixture(scope="session")
def browser(api_url: str) -> Iterator[Browser]:
    with httpx.Client(base_url=api_url) as client:
        client.get("/health/ready").raise_for_status()
    with sync_playwright() as runtime:
        instance = runtime.chromium.launch()
        yield instance
        instance.close()


@pytest.fixture
def page(
    browser: Browser, api_url: str, request: pytest.FixtureRequest
) -> Iterator[Page]:
    context = browser.new_context(
        base_url=api_url, viewport={"width": 1440, "height": 1000}
    )
    context.tracing.start(screenshots=True, snapshots=True)
    tab = context.new_page()
    errors: list[str] = []
    console: list[str] = []
    tab.on("console", lambda entry: console.append(f"{entry.type}: {entry.text}"))
    tab.on("pageerror", lambda error: errors.append(str(error)))
    yield tab
    artifact = Path(os.environ["CARDREPORT_TEST_ARTIFACTS"])
    stem = "ui-" + request.node.name.replace("/", "-")
    # Keep traces for all cases; harness retains the run on failure or --keep.
    tab.screenshot(path=str(artifact / (stem + ".png")), full_page=True)
    context.tracing.stop(path=str(artifact / (stem + ".zip")))
    (artifact / (stem + ".log")).write_text("\n".join(console))
    context.close()
    assert not errors, errors
