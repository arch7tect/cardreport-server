from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError

from cardreport_server.db import Database
from cardreport_server.maintenance import OrphanSweep
from cardreport_server.settings import Settings
from cardreport_server.storage import Storage

pytestmark = pytest.mark.integration


def test_orphan_pages_and_cursor_reset(
    database: Database,
    storage: Storage,
    integration_settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = tmp_path / "orphan"
    payload.write_bytes(b"fixture")
    old = storage.prefix + "inputs/" + uuid4().hex
    young = storage.prefix + "inputs/" + uuid4().hex
    unrelated = storage.prefix + "user-owned/" + uuid4().hex
    for key in (old, young, unrelated):
        storage.put(key, payload, "application/json")
    now = datetime.now(UTC)
    original = storage.client.list_objects_v2
    calls: list[dict[str, Any]] = []

    def listing(**kwargs: Any) -> Any:
        calls.append(kwargs)
        if len(calls) == 1:
            return {
                "Contents": [
                    {"Key": old, "LastModified": now - timedelta(days=2)},
                    {"Key": young, "LastModified": now},
                    {"Key": unrelated, "LastModified": now - timedelta(days=2)},
                ],
                "NextContinuationToken": "cursor",
            }
        raise ClientError(
            {"Error": {"Code": "InvalidToken", "Message": "test"}}, "ListObjectsV2"
        )

    monkeypatch.setattr(storage.client, "list_objects_v2", listing)
    sweep = OrphanSweep()
    sweep.run(database, storage, integration_settings)
    assert sweep.cursor == "cursor"
    with pytest.raises(ClientError):
        storage.get(old)
    for key in (young, unrelated):
        body = storage.get(key)
        assert body.read() == b"fixture"
        body.close()
    with pytest.raises(ClientError):
        sweep.run(database, storage, integration_settings)
    assert calls[-1]["ContinuationToken"] == "cursor" and sweep.cursor is None
    monkeypatch.setattr(storage.client, "list_objects_v2", original)
    for key in (young, unrelated):
        storage.delete(key)
