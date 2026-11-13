"""Bounded views of the immutable data snapshot committed with a report."""

import time
from datetime import date
from typing import cast
from uuid import UUID

from cardreport import DataError, Dataset, datasets_from_json
from fastapi import Request
from starlette.concurrency import run_in_threadpool

from . import dependencies as deps
from .datasets import SNAPSHOT_LIMIT
from .downloads import artifact_row
from .errors import APIError
from .storage import read_verified


def _read_snapshot(request: Request, report_id: UUID) -> dict[str, Dataset]:
    db = deps.database(request)
    deadline = time.monotonic() + deps.settings(request).download_timeout
    row = artifact_row(db, report_id, "data")
    size = row["data_size"]
    if not isinstance(size, int) or not 0 < size <= SNAPSHOT_LIMIT:
        raise APIError(503, "data_integrity", "Saved dataset snapshot is invalid")
    raw = read_verified(
        deps.storage(request).get(cast(str, row["data_key"])),
        size,
        cast(str, row["data_hash"]),
        deadline,
        integrity=APIError(503, "data_integrity", "Saved dataset snapshot is invalid"),
        timeout=APIError(504, "data_timeout", "Reading report data timed out"),
    )
    try:
        # Operators may lower input limits but cannot raise the library ceilings.
        datasets = datasets_from_json(raw)
    except DataError:
        raise APIError(
            503, "data_integrity", "Saved dataset snapshot is invalid"
        ) from None
    if time.monotonic() >= deadline:
        raise APIError(504, "data_timeout", "Reading report data timed out")
    artifact_row(db, report_id, "data")
    return datasets


async def read_snapshot(request: Request, report_id: UUID) -> dict[str, Dataset]:
    limiter = deps.data_view_limiter(request)
    with deps.slot(
        limiter,
        APIError(503, "data_view_busy", "Report data viewers are busy; try again"),
    ):
        return await run_in_threadpool(_read_snapshot, request, report_id)


def display_cell(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
