"""Keyset pagination over retained reports, independent of cursor-row lifetime."""

import base64
import binascii
import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from .db import Database
from .errors import APIError

State = Literal["queued", "running", "succeeded", "failed", "expired"]
STATUS_COLUMNS = """id,template_id,template_version,state,output_kind AS output,renderer,
attempt_no AS attempts,created_at,started_at,finished_at,result_expires_at,
error,terminal_state,engine_version,image_id,service_version,
(data_key IS NOT NULL AND NOT result_deleted AND state='succeeded' AND result_expires_at>clock_timestamp()) AS data_available"""


def decode_cursor(value: str) -> tuple[datetime, UUID]:
    try:
        if not 1 <= len(value) <= 512:
            raise ValueError
        raw = base64.b64decode(
            value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
        )
        parts = json.loads(raw)
        if (
            not isinstance(parts, list)
            or len(parts) != 3
            or type(parts[0]) is not int
            or parts[0] != 1
            or not isinstance(parts[1], str)
            or not isinstance(parts[2], str)
        ):
            raise ValueError
        created = datetime.fromisoformat(parts[1])
        if created.tzinfo is None:
            raise ValueError
        return created.astimezone(UTC), UUID(parts[2])
    except (ValueError, TypeError, OverflowError, binascii.Error):
        raise APIError(
            422, "invalid_cursor", "Report history cursor is invalid"
        ) from None


def encode_cursor(row: dict[str, Any]) -> str:
    raw = json.dumps([1, row["created_at"].isoformat(), str(row["id"])])
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def list_reports(
    db: Database,
    *,
    template_id: str | None,
    state: State | None,
    after: str | None,
    limit: int,
) -> dict[str, Any]:
    clauses = []
    params: list[object] = []
    if template_id is not None:
        clauses.append("template_id=%s")
        params.append(template_id)
    if state is not None:
        clauses.append("state=%s")
        params.append(state)
    if after is not None:
        clauses.append("(created_at,id)<(%s,%s)")
        params.extend(decode_cursor(after))
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    # Only fixed SQL fragments are composed; every caller value remains a parameter.
    query = f"SELECT {STATUS_COLUMNS} FROM reports{where} ORDER BY created_at DESC,id DESC LIMIT %s"
    params.append(limit + 1)
    with db.pool.connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return {
        "items": rows[:limit],
        "next": encode_cursor(rows[limit - 1]) if len(rows) > limit else None,
    }
