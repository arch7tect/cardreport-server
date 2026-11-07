import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from playwright.sync_api import Page, Route, expect

from cardreport_server.db import Database
from cardreport_server.storage import Storage
from cardreport_server.templates import register

pytestmark = pytest.mark.ui


def test_preview_isolation_and_navigation_limit(
    page: Page,
    database: Database,
    storage: Storage,
    template_spec: dict[str, object],
    tmp_path: Path,
) -> None:
    slug = "ui-isolation-" + uuid4().hex
    identifier = str(uuid4())
    register(database, slug, json.dumps(template_spec).encode(), "application/json")
    payload = b"""<!doctype html><html><body><h1>Isolation fixture</h1><a href="/canary?self">Navigate self</a><script>
    try { parent.document.body.dataset.escaped = 'yes'; } catch { document.body.dataset.parentBlocked = 'yes'; }
    try { localStorage.setItem('escaped','yes'); } catch { document.body.dataset.storageBlocked = 'yes'; }
    fetch('/v1/templates?canary=fetch').catch(()=>{document.body.dataset.fetchBlocked='yes'});
    const img = new Image(); img.src='/canary?image'; document.body.append(img);
    const script = document.createElement('script'); script.src='/canary?script'; document.body.append(script);
    try { window.open('/canary?popup'); } catch {}
    if (window !== parent) { try { top.location='/canary?top'; } catch {} }
    </script></body></html>"""
    result = tmp_path / "isolation.html"
    result.write_bytes(payload)
    key = storage.prefix + "results/" + identifier
    storage.put(key, result, "text/html")
    with database.pool.connection() as conn:
        conn.execute(
            """INSERT INTO reports(id,template_id,template_version,state,input_key,input_type,input_size,input_hash,output_kind,input_retention,result_retention,metadata_retention,result_key,result_size,result_hash,result_expires_at)
            VALUES(%s,%s,1,'succeeded',%s,'application/json',2,'test','html',60,60,120,%s,%s,%s,clock_timestamp()+interval '1 hour')""",
            (
                identifier,
                slug,
                "test/unused/" + identifier,
                key,
                len(payload),
                hashlib.sha256(payload).hexdigest(),
            ),
        )
    escaped_requests: list[str] = []

    def canary(route: Route) -> None:
        escaped_requests.append(route.request.url)
        route.fulfill(
            content_type="text/html",
            body="<html><body>Harmless navigation target</body></html>",
        )

    page.context.route("**/*canary*", canary)
    page.goto(f"/ui/#/reports/{identifier}")
    page.get_by_role("button", name="Preview HTML").click()
    frame = page.frame_locator('iframe[title="Report preview"]')
    expect(frame.locator("body")).to_have_attribute("data-parent-blocked", "yes")
    expect(frame.locator("body")).to_have_attribute("data-storage-blocked", "yes")
    expect(frame.locator("body")).to_have_attribute("data-fetch-blocked", "yes")
    assert page.locator("body").get_attribute("data-escaped") is None
    assert len(page.context.pages) == 1
    assert not escaped_requests
    original = page.url
    frame.get_by_role("link", name="Navigate self").click()
    expect(frame.get_by_text("Harmless navigation target")).to_be_visible()
    assert len(escaped_requests) == 1 and escaped_requests[0].endswith("?self")
    assert page.url == original
    # HTTP sandbox also applies on direct preview entry, without a console iframe.
    page.goto(f"/v1/reports/{identifier}/content?disposition=inline")
    expect(page.locator("body")).to_have_attribute("data-storage-blocked", "yes")
    expect(page.locator("body")).to_have_attribute("data-fetch-blocked", "yes")
    assert len(escaped_requests) == 1
    assert len(page.context.pages) == 1
