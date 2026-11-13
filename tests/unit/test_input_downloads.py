import asyncio
import hashlib
import io
import time
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import anyio
import pytest
from starlette.requests import Request

from cardreport_server import input_view
from cardreport_server.errors import APIError


@pytest.mark.parametrize(
    "fault", ["size", "hash", "deadline", "expiry", "empty", "oversized_chunk", "ok"]
)
def test_input_read_bounds_and_recheck(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    raw = b"" if fault == "empty" else b"private original"
    body = io.BytesIO(raw)
    if fault == "oversized_chunk":
        body.read = Mock(return_value=b"x" * 70000)  # type: ignore[method-assign]
    row = {
        "input_size": len(raw) if fault != "size" else 3,
        "input_hash": hashlib.sha256(raw).hexdigest() if fault != "hash" else "wrong",
        "input_key": "key",
    }
    lookup = Mock(return_value=row)
    if fault == "expiry":
        lookup.side_effect = [row, APIError(410, "input_expired", "Expired")]
    monkeypatch.setattr(input_view, "input_row", lookup)
    app = SimpleNamespace(
        state=SimpleNamespace(storage=SimpleNamespace(get=lambda _: body))
    )
    request = Request({"type": "http", "app": app})
    deadline = time.monotonic() + (100 if fault != "deadline" else -1)
    if fault in {"ok", "empty"}:
        assert input_view._prepare(request, uuid4(), "raw", None, deadline)[0] == raw
        assert lookup.call_count == 2
    else:
        with pytest.raises(APIError) as caught:
            input_view._prepare(request, uuid4(), "raw", None, deadline)
        assert caught.value.status == {"deadline": 504, "expiry": 410}.get(fault, 503)
        assert caught.value.code == {
            "deadline": "input_timeout",
            "expiry": "input_expired",
        }.get(fault, "input_integrity")
        assert caught.value.message == {
            "deadline": "Reading report inputs timed out",
            "expiry": "Expired",
        }.get(fault, "Saved input is invalid")
    assert body.closed


def test_input_response_holds_capacity_until_delivery() -> None:
    async def run() -> None:
        limiter = anyio.CapacityLimiter(1)
        borrower = object()
        limiter.acquire_on_behalf_of_nowait(borrower)
        request = Request(
            {
                "type": "http",
                "app": SimpleNamespace(
                    state=SimpleNamespace(data_view_limiter=limiter)
                ),
            }
        )
        response = input_view.InputResponse(
            b"data",
            request=request,
            borrower=borrower,
            deadline=time.monotonic() + 0.02,
        )

        async def send(message: object) -> None:
            assert limiter.borrowed_tokens == 1
            await anyio.sleep(1)

        async def receive() -> dict[str, str]:
            return {"type": "http.disconnect"}

        with pytest.raises(TimeoutError):
            await response({"type": "http"}, receive, send)
        assert limiter.borrowed_tokens == 0

    asyncio.run(run())
