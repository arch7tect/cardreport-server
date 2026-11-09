"""Real TCP assertions for the raw streaming request path."""

import json
import socket
import threading
import time
from collections.abc import Iterator
from uuid import uuid4

import httpx
import pytest
import uvicorn

from cardreport_server.api import create_app
from cardreport_server.db import Database
from cardreport_server.settings import Settings
from cardreport_server.templates import register

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "content_type", ["application/json", "multipart/form-data; boundary=test"]
)
def test_tcp_streams(
    integration_settings: Settings,
    database: Database,
    template_spec: dict[str, object],
    content_type: str,
) -> None:
    settings = integration_settings.model_copy(
        update={
            "upload_slots": 1,
            "input_limit": 512,
            "upload_idle_timeout": 0.25,
            "upload_timeout": 2,
        }
    )
    app = create_app(settings)
    slug = "tcp-" + uuid4().hex
    register(database, slug, json.dumps(template_spec).encode(), "application/json")
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
        url = f"http://127.0.0.1:{port}/v1/reports?template_id={slug}"
        headers = {"Content-Type": content_type}
        response = httpx.post(url, content=iter([b"{", b"}"]), headers=headers)
        assert response.status_code == 202
        assert (
            httpx.post(
                url, content=iter([b"x" * 300, b"x" * 300]), headers=headers
            ).status_code
            == 413
        )
        raw = socket.create_connection(("127.0.0.1", port))
        raw.sendall(
            f"POST /v1/reports?template_id={slug} HTTP/1.1\r\nHost: localhost\r\nContent-Type: {content_type}\r\nTransfer-Encoding: chunked\r\n\r\n1\r\nx\r\n".encode()
        )
        time.sleep(0.05)
        assert httpx.post(url, content=b"{}", headers=headers).status_code == 429
        raw.settimeout(3)
        assert b"408" in raw.recv(8192)
        raw.close()
        interrupted = socket.create_connection(("127.0.0.1", port))
        interrupted.sendall(
            f"POST /v1/reports?template_id={slug} HTTP/1.1\r\nHost: localhost\r\nContent-Type: {content_type}\r\nContent-Length: 500\r\n\r\nx".encode()
        )
        interrupted.close()
        time.sleep(0.1)
        with database.pool.connection() as conn:
            row = conn.execute(
                "SELECT count(*) AS n FROM reports WHERE template_id=%s", (slug,)
            ).fetchone()
        assert row is not None and row["n"] == 1

        def slow() -> Iterator[bytes]:
            yield b"x"
            time.sleep(0.35)
            yield b"x"

        assert httpx.post(url, content=slow(), headers=headers).status_code == 408
    finally:
        server.should_exit = True
        thread.join(10)
        listener.close()
        assert not thread.is_alive()
