import json
import re
from uuid import uuid4

import pytest
from playwright.sync_api import Page, Route, expect

pytestmark = pytest.mark.ui


def report(identifier: str, state: str) -> dict[str, object]:
    return {
        "id": identifier,
        "template_id": "sample",
        "template_version": 1,
        "state": state,
        "output": "html",
        "renderer": "chromium",
        "attempts": 1,
        "created_at": "2026-11-07T00:00:00Z",
        "started_at": None,
        "finished_at": None,
        "result_expires_at": None,
        "error": None,
        "terminal_state": None,
        "engine_version": None,
        "service_version": None,
        "image_id": None,
    }


def test_polling_visibility_errors_and_navigation(page: Page) -> None:
    identifier = str(uuid4())
    states = ["running", "queued", "failed"]
    count = 0

    def respond(route: Route) -> None:
        nonlocal count
        index = count
        count += 1
        if index == 0:
            route.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps(
                    {"error": {"code": "unavailable", "message": "Try later"}}
                ),
                headers={"Retry-After": "1"},
            )
        else:
            route.fulfill(json=report(identifier, states[min(index - 1, 2)]))

    page.route(f"**/v1/reports/{identifier}", respond)
    page.clock.install()
    page.goto(f"/ui/#/reports/{identifier}")
    expect(page.get_by_text("Status is stale.", exact=False)).to_be_visible()
    page.get_by_role("button", name="Refresh status").click()
    expect(page.locator(".badge.running")).to_be_visible()
    page.evaluate(
        "Object.defineProperty(document, 'hidden', {configurable:true,get:()=>true}); document.dispatchEvent(new Event('visibilitychange'))"
    )
    before = count
    page.clock.run_for(20000)
    assert count == before
    page.evaluate(
        "Object.defineProperty(document, 'hidden', {configurable:true,get:()=>false}); document.dispatchEvent(new Event('visibilitychange'))"
    )
    expect(page.locator(".badge.queued")).to_be_visible()
    page.clock.run_for(2001)
    expect(page.locator(".badge.failed")).to_be_visible()
    before = count
    page.clock.run_for(20000)
    assert count == before
    page.get_by_role("link", name="Templates", exact=True).first.click()
    page.clock.run_for(20000)
    assert count == before


def test_stale_response_does_not_replace_new_screen(page: Page) -> None:
    identifier = str(uuid4())
    pending: list[Route] = []
    page.route(f"**/v1/reports/{identifier}", lambda route: pending.append(route))
    page.goto(f"/ui/#/reports/{identifier}")
    expect(page.get_by_role("heading", name="Report details")).to_be_visible()
    page.get_by_role("link", name="Templates", exact=True).first.click()
    expect(page.get_by_role("heading", name="Templates", exact=True)).to_be_visible()
    assert pending
    pending[0].fulfill(json=report(identifier, "running"))
    expect(page.get_by_role("heading", name="Templates", exact=True)).to_be_visible()


@pytest.mark.parametrize(
    "code,message",
    [
        (413, "Input too large"),
        (415, "Wrong format"),
        (422, "Invalid input"),
        (429, "Busy"),
        (503, "Service down"),
    ],
)
def test_submission_errors_preserve_draft(page: Page, code: int, message: str) -> None:
    count = 0

    def submit(route: Route) -> None:
        nonlocal count
        count += 1
        route.fulfill(
            status=code,
            json={"error": {"code": "test_failure", "message": message}},
            headers={"Retry-After": "2"},
        )

    page.route(
        "**/v1/templates/sample",
        lambda route: route.fulfill(
            json={"id": "sample", "latest_version": 1, "archived": False}
        ),
    )
    page.route(
        "**/v1/templates/sample/versions*",
        lambda route: route.fulfill(json={"items": [], "next": None}),
    )
    page.route("**/v1/reports?*", submit)
    page.goto("/ui/#/new-report?template=sample&version=1")
    page.get_by_label("Data input", exact=True).select_option("paste")
    page.get_by_label("Dataset source", exact=True).fill(
        '{"format":"cardreport.data/1","datasets":{}}'
    )
    page.get_by_role("button", name="Generate report", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text(
        "Acceptance is uncertain" if code == 503 else message
    )
    expect(page.get_by_label("Dataset source", exact=True)).to_have_value(
        '{"format":"cardreport.data/1","datasets":{}}'
    )
    assert count == 1


def test_pagination_beyond_first_page(page: Page) -> None:
    def templates(route: Route) -> None:
        after = "after=first" in route.request.url
        route.fulfill(
            json={
                "items": [
                    {
                        "id": "second" if after else "first",
                        "latest_version": 55,
                        "archived": False,
                        "created_at": None,
                    }
                ],
                "next": None if after else "first",
            }
        )

    page.route("**/v1/templates?*", templates)
    page.route(
        "**/v1/templates/second",
        lambda route: route.fulfill(
            json={"id": "second", "latest_version": 55, "archived": False}
        ),
    )

    def versions(route: Route) -> None:
        after = "after=50" in route.request.url
        route.fulfill(
            json={
                "items": [{"version": 51 if after else 1}],
                "next": None if after else 50,
            }
        )

    page.route("**/v1/templates/second/versions?*", versions)
    page.goto("/ui/#/new-report")
    page.get_by_role("button", name="Load more templates").click()
    page.get_by_label("Template", exact=True).select_option("second")
    expect(page.get_by_label("Template version", exact=True)).to_have_value("55")
    page.get_by_role("button", name="Load more versions").click()
    page.get_by_label("Template version", exact=True).select_option("51")
    expect(page.get_by_label("Template version", exact=True)).to_have_value("51")


def test_expired_and_missing_detail(page: Page) -> None:
    identifier = str(uuid4())
    row = report(identifier, "expired") | {"terminal_state": "failed"}
    page.route(f"**/v1/reports/{identifier}", lambda route: route.fulfill(json=row))
    page.goto(f"/ui/#/reports/{identifier}")
    expect(page.locator(".badge.expired")).to_contain_text("failed")
    expect(page.get_by_role("button", name="Preview HTML")).to_be_hidden()
    page.unroute(f"**/v1/reports/{identifier}")
    page.route(
        f"**/v1/reports/{identifier}",
        lambda route: route.fulfill(
            status=404,
            json={"error": {"code": "report_not_found", "message": "Missing"}},
        ),
    )
    page.get_by_role("button", name="Refresh status").click()
    expect(
        page.get_by_text(
            "This report does not exist or its metadata has expired.", exact=True
        )
    ).to_be_visible()


def test_history_filter_resets_cursor(page: Page) -> None:
    first, second = str(uuid4()), str(uuid4())
    requests: list[str] = []

    def history(route: Route) -> None:
        requests.append(route.request.url)
        later = "after=next-page" in route.request.url
        route.fulfill(
            json={
                "items": [report(second if later else first, "failed")],
                "next": None if later else "next-page",
            }
        )

    page.route("**/v1/reports*", history)
    page.goto("/ui/#/reports")
    page.get_by_role("button", name="Load more", exact=True).click()
    expect(page.get_by_role("link", name=second[:8], exact=True)).to_be_visible()
    page.get_by_label("State", exact=True).select_option("failed")
    expect(page.get_by_role("link", name=second[:8], exact=True)).to_have_count(0)
    assert "state=failed" in requests[-1] and "after=" not in requests[-1]


def test_permanent_status_error_does_not_poll(page: Page) -> None:
    count = 0

    def invalid(route: Route) -> None:
        nonlocal count
        count += 1
        route.fulfill(
            status=422,
            json={
                "error": {"code": "invalid_request", "message": "Invalid identifier"}
            },
        )

    page.route("**/v1/reports/invalid-id", invalid)
    page.clock.install()
    page.goto("/ui/#/reports/invalid-id")
    expect(page.get_by_text("Invalid identifier", exact=False)).to_be_visible()
    page.clock.run_for(60000)
    assert count == 1


@pytest.mark.parametrize("screen", ["templates", "reports"])
def test_failed_filter_clears_previous_page(page: Page, screen: str) -> None:
    identifier = str(uuid4())
    count = 0

    def respond(route: Route) -> None:
        nonlocal count
        count += 1
        if count > 1:
            route.fulfill(status=503, json={"error": {"message": "Try later"}})
        else:
            row = (
                report(identifier, "queued")
                if screen == "reports"
                else {
                    "id": "old-template",
                    "archived": False,
                    "latest_version": 1,
                    "created_at": None,
                }
            )
            route.fulfill(json={"items": [row], "next": "old-cursor"})

    page.route(re.compile(rf"/v1/{screen}(?:\?.*)?$"), respond)
    page.goto(f"/ui/#/{screen}")
    expect(page.locator("tbody tr")).to_have_count(1)
    page.get_by_label(
        "State" if screen == "reports" else "Show", exact=True
    ).select_option("failed" if screen == "reports" else "true")
    expect(page.get_by_text("Try later", exact=False)).to_be_visible()
    expect(page.locator("tbody tr")).to_have_count(0)
    expect(page.get_by_role("button", name="Load more", exact=True)).to_be_hidden()


def test_background_poll_preserves_focus(page: Page) -> None:
    identifier = str(uuid4())
    count = 0

    def respond(route: Route) -> None:
        nonlocal count
        count += 1
        if count == 1:
            route.fulfill(json=report(identifier, "running"))
        else:
            route.fulfill(status=503, json={"error": {"message": "Try later"}})

    page.route(f"**/v1/reports/{identifier}", respond)
    page.clock.install()
    page.goto(f"/ui/#/reports/{identifier}")
    expect(page.locator(".badge.running")).to_be_visible()
    target = page.get_by_role("button", name="Copy ID", exact=True)
    target.focus()
    page.clock.run_for(2001)
    expect(page.get_by_text("Status is stale.", exact=False)).to_be_visible()
    expect(target).to_be_focused()


def test_template_version_pagination_reload_and_new_id(page: Page) -> None:
    page.route(
        "**/v1/templates/new",
        lambda route: route.fulfill(
            json={"id": "new", "latest_version": 51, "archived": False}
        ),
    )
    page.route(
        "**/v1/templates/new/versions?*",
        lambda route: route.fulfill(
            json={
                "items": [{"version": 51 if "after=50" in route.request.url else 1}],
                "next": None if "after=50" in route.request.url else 50,
            }
        ),
    )
    page.route(
        "**/v1/templates/new/versions/*",
        lambda route: route.fulfill(
            json={
                "version": int(route.request.url.rsplit("/", 1)[1]),
                "definition": {"title": "<script>bad()</script>"},
                "created_at": None,
                "digest": "test",
                "validated_with": "test",
            }
        ),
    )
    page.goto("/ui/#/templates/new?version=1")
    expect(page.get_by_role("heading", name="new", exact=True)).to_be_visible()
    page.get_by_role("button", name="Load more versions").click()
    page.get_by_label("Version", exact=True).select_option("51")
    expect(page.get_by_text("v51", exact=True)).to_be_visible()
    page.reload()
    expect(page.get_by_label("Version", exact=True)).to_have_value("51")
    expect(page.locator("pre")).to_contain_text("<script>bad()</script>")


@pytest.mark.parametrize("status", [409, 422])
def test_template_save_errors_keep_source(page: Page, status: int) -> None:
    page.route(
        "**/v1/templates/sample/versions",
        lambda route: route.fulfill(
            status=status,
            json={
                "error": {
                    "code": "archived" if status == 409 else "invalid_template",
                    "message": "Cannot save",
                    "template_path": "$.pages[0]",
                }
            },
        ),
    )
    page.goto("/ui/#/create-template")
    page.get_by_label("Template ID", exact=True).fill("sample")
    page.get_by_label("Template source", exact=True).fill('{"draft": true}')
    page.get_by_role("button", name="Save new version").click()
    expect(page.get_by_role("status")).to_contain_text("$.pages[0]")
    expect(page.get_by_label("Template source", exact=True)).to_have_value(
        '{"draft": true}'
    )
