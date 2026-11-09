"""Bounded views of the immutable data snapshot committed with a report."""

import hashlib
import time
from datetime import date
from uuid import UUID

import anyio
from cardreport import DataError, Dataset, datasets_from_json
from fastapi import Request
from starlette.concurrency import run_in_threadpool

from .datasets import SNAPSHOT_LIMIT
from .downloads import artifact_row
from .errors import APIError


def _read_snapshot(request: Request, report_id: UUID) -> dict[str, Dataset]:
    db = request.app.state.database
    deadline = time.monotonic() + request.app.state.settings.download_timeout
    row = artifact_row(db, report_id, "data")
    size = row["data_size"]
    if not isinstance(size, int) or not 0 < size <= SNAPSHOT_LIMIT:
        raise APIError(503, "data_integrity", "Saved dataset snapshot is invalid")
    body = request.app.state.storage.get(row["data_key"])
    raw = bytearray()
    digest = hashlib.sha256()
    try:
        while True:
            if time.monotonic() >= deadline:
                raise APIError(504, "data_timeout", "Reading report data timed out")
            chunk = body.read(min(64 * 1024, size + 1 - len(raw)))
            if not chunk:
                break
            if len(raw) + len(chunk) > size:
                raise APIError(
                    503, "data_integrity", "Saved dataset snapshot is invalid"
                )
            raw.extend(chunk)
            digest.update(chunk)
    finally:
        body.close()
    if len(raw) != size or digest.hexdigest() != row["data_hash"]:
        raise APIError(503, "data_integrity", "Saved dataset snapshot is invalid")
    try:
        # Operators may lower input limits but cannot raise the library ceilings.
        datasets = datasets_from_json(bytes(raw))
    except DataError:
        raise APIError(
            503, "data_integrity", "Saved dataset snapshot is invalid"
        ) from None
    if time.monotonic() >= deadline:
        raise APIError(504, "data_timeout", "Reading report data timed out")
    artifact_row(db, report_id, "data")
    return datasets


async def read_snapshot(request: Request, report_id: UUID) -> dict[str, Dataset]:
    limiter = request.app.state.data_view_limiter
    try:
        limiter.acquire_nowait()
    except anyio.WouldBlock:
        raise APIError(
            503, "data_view_busy", "Report data viewers are busy; try again"
        ) from None
    try:
        return await run_in_threadpool(_read_snapshot, request, report_id)
    finally:
        limiter.release()


def display_cell(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
