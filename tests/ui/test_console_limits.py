import json
import re
import socket
import threading
import time
from uuid import uuid4

import pytest
import uvicorn
from playwright.sync_api import Page, expect

from cardreport_server.api import create_app
from cardreport_server.db import Database
from cardreport_server.settings import Settings
from cardreport_server.templates import register

pytestmark = pytest.mark.ui


def test_real_early_upload_limit(
    page: Page,
    integration_settings: Settings,
    database: Database,
    template_spec: dict[str, object],
) -> None:
    slug = "ui-limit-" + uuid4().hex
    register(database, slug, json.dumps(template_spec).encode(), "application/json")
    app = create_app(integration_settings.model_copy(update={"input_limit": 512}))
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="critical", lifespan="on", access_log=False)
    )
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [listener]}, daemon=True
    )
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            assert thread.is_alive() and time.monotonic() < deadline
            time.sleep(0.01)
        count = []
        page.on(
            "request",
            lambda request: count.append(request) if request.method == "POST" else None,
        )
        page.goto(f"http://127.0.0.1:{port}/ui/#/new-report?template={slug}")
        page.get_by_label("Data files", exact=True).set_input_files(
            {
                "name": "too-large.json",
                "mimeType": "application/json",
                "buffer": b"x" * 1024 * 1024,
            }
        )
        page.get_by_role("button", name="Generate report", exact=True).click()
        expect(page.get_by_role("status")).not_to_contain_text("Sending")
        expect(page.get_by_role("status")).to_contain_text(
            re.compile("limit|Acceptance is uncertain")
        )
        expect(page.get_by_label("Selected files").locator("li")).not_to_have_count(0)
        assert len(count) == 1
        with database.pool.connection() as conn:
            row = conn.execute(
                "SELECT count(*) AS n FROM reports WHERE template_id=%s", (slug,)
            ).fetchone()
        assert row is not None and row["n"] == 0
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
        assert not thread.is_alive()
