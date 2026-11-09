import hashlib
import io
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from starlette.requests import Request

from cardreport_server import data_view
from cardreport_server.errors import APIError


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        (True, "true"),
        (False, "false"),
        (9007199254740993, "9007199254740993"),
        (Decimal("1E+3"), "1E+3"),
        (Decimal("1E-999999999"), "1E-999999999"),
        (Decimal("0.123456789123456789"), "0.123456789123456789"),
        (1.25, "1.25"),
        (date(2026, 11, 9), "2026-11-09"),
        (datetime(2026, 11, 9, tzinfo=UTC), "2026-11-09T00:00:00+00:00"),
        ("<script>", "<script>"),
    ],
)
def test_exact_display(value: object, expected: str | None) -> None:
    assert data_view.display_cell(value) == expected


@pytest.mark.parametrize("fault", ["size", "hash", "invalid", "deadline", "ok"])
def test_snapshot_read_closes_and_verifies(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    raw = (
        b'{"format":"cardreport.data/1","datasets":{}}' if fault != "invalid" else b"{}"
    )
    body = io.BytesIO(raw)
    lookup = Mock(
        return_value={
            "data_size": len(raw) if fault != "size" else len(raw) - 1,
            "data_hash": hashlib.sha256(raw).hexdigest()
            if fault != "hash"
            else "wrong",
            "data_key": "key",
        }
    )
    monkeypatch.setattr(data_view, "artifact_row", lookup)
    app = SimpleNamespace(
        state=SimpleNamespace(
            database=object(),
            settings=SimpleNamespace(download_timeout=10),
            storage=SimpleNamespace(get=lambda _: body),
        )
    )
    if fault == "deadline":
        ticks = iter([0, 20])
        monkeypatch.setattr(
            "cardreport_server.data_view.time.monotonic", lambda: next(ticks)
        )
    if fault == "ok":
        assert (
            data_view._read_snapshot(Request({"type": "http", "app": app}), uuid4())
            == {}
        )
        assert lookup.call_count == 2
    else:
        with pytest.raises(APIError) as caught:
            data_view._read_snapshot(Request({"type": "http", "app": app}), uuid4())
        assert caught.value.status == (504 if fault == "deadline" else 503)
    assert body.closed
