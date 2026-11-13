"""Retained originals and bounded investigation bundles, including failed jobs."""

import io
import json
import tempfile
import time
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import anyio
from cardreport import DataError, DataLimits
from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from . import dependencies as deps
from .errors import APIError
from .input_files import extract_parts
from .storage import read_verified

router = APIRouter(prefix="/v1/reports", tags=["Reports"])


def input_row(request: Request, report_id: UUID) -> dict[str, Any]:
    with deps.database(request).pool.connection() as conn:
        row = conn.execute(
            """SELECT r.*, input_expires_at>clock_timestamp() AS available,
            v.definition::text AS template_definition
            FROM reports r JOIN template_versions v ON v.template_id=r.template_id
            AND v.version=r.template_version WHERE r.id=%s""",
            (report_id,),
        ).fetchone()
    if row is None:
        raise APIError(404, "report_not_found", "Report does not exist")
    if (
        row["input_deleted"]
        or row["state"] == "expired"
        or (row["input_expires_at"] is not None and not row["available"])
    ):
        raise APIError(410, "input_expired", "Report input expired")
    return dict(row)


def _prepare(
    request: Request, report_id: UUID, kind: str, index: int | None, deadline: float
) -> tuple[bytes | memoryview, str]:
    def check_time() -> None:
        if time.monotonic() >= deadline:
            raise APIError(504, "input_timeout", "Reading report inputs timed out")

    row = input_row(request, report_id)
    size = row["input_size"]
    # Retained uploads remain readable after an operator lowers admission limits.
    if not isinstance(size, int) or not 0 <= size <= DataLimits().max_json_bytes:
        raise APIError(503, "input_integrity", "Saved input is invalid")
    raw = read_verified(
        deps.storage(request).get(row["input_key"]),
        size,
        row["input_hash"],
        deadline,
        integrity=APIError(503, "input_integrity", "Saved input is invalid"),
        timeout=APIError(504, "input_timeout", "Reading report inputs timed out"),
    )
    filename = "input.raw"
    payload: bytes | memoryview = raw
    if kind != "raw":
        parts = None
        with tempfile.TemporaryDirectory(prefix="cardreport-input-") as directory:
            path = Path(directory) / "input"
            path.write_bytes(raw)
            try:
                parts = extract_parts(path, row["input_type"])
            except DataError:
                pass
        results = {r["id"]: r for r in row["input_files"] or []}
        catalog = {
            "structure": "valid" if parts is not None else "invalid",
            "content_type": row["input_type"],
            "size": size,
            "sha256": row["input_hash"],
            "expires_at": row["input_expires_at"],
            "fields": parts.fields if parts else [],
            "files": [
                f.describe()
                | results.get(
                    f.id, {"status": "unknown", "datasets": [], "error": None}
                )
                for f in parts.files
            ]
            if parts
            else [],
        }
        if kind == "catalog":
            payload = json.dumps(catalog, default=str).encode()
            filename = "files.json"
        elif kind == "file":
            selected = (
                next((f for f in parts.files if f.id == index), None) if parts else None
            )
            if selected is None:
                raise APIError(
                    404,
                    "file_not_found",
                    "Input file is unavailable; download the original request",
                )
            payload = selected.content
            # The original name remains in the catalog; never put client text in headers.
            suffix = Path(selected.name).suffix.lower()
            filename = f"input-{selected.id}" + (
                suffix if suffix in {".csv", ".json", ".yaml", ".yml"} else ".bin"
            )
        else:
            manifest = {
                "report_id": str(report_id),
                "template_id": row["template_id"],
                "template_version": row["template_version"],
                "renderer": row["renderer"],
                "output": row["output_kind"],
                "state": row["state"],
                "error": row["error"],
                "engine_version": row["engine_version"],
                "service_version": row["service_version"],
                "image_id": row["image_id"],
                "input": catalog,
            }
            archive = io.BytesIO()
            with zipfile.ZipFile(
                archive, "w", compression=zipfile.ZIP_STORED
            ) as bundle:
                # Fixed generated paths and timestamps preserve duplicate names safely.
                def put(name: str, content: bytes) -> None:
                    bundle.writestr(zipfile.ZipInfo(name), content)

                put("input.raw", raw)
                put("template.json", row["template_definition"].encode())
                if parts:
                    for file in parts.files:
                        put(f"files/{file.id}", file.content)
                put(
                    "manifest.json",
                    json.dumps(manifest, default=str, indent=2).encode(),
                )
            payload = archive.getbuffer()
            filename = f"report-{report_id}-inputs.zip"
    check_time()
    input_row(request, report_id)
    return payload, filename


class InputResponse(Response):
    def __init__(
        self,
        content: bytes | memoryview,
        *,
        request: Request,
        borrower: object,
        deadline: float,
        media_type: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(content, media_type=media_type, headers=headers)
        self.limiter = deps.data_view_limiter(request)
        self.borrower = borrower
        self.deadline = deadline

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            with anyio.fail_after(max(0, self.deadline - time.monotonic())):
                await super().__call__(scope, receive, send)
        finally:
            self.limiter.release_on_behalf_of(self.borrower)


async def read_input(
    request: Request,
    report_id: UUID,
    kind: Literal["raw", "catalog", "file", "zip"],
    index: int | None = None,
) -> Response:
    limiter = deps.data_view_limiter(request)
    borrower = object()
    try:
        limiter.acquire_on_behalf_of_nowait(borrower)
    except anyio.WouldBlock:
        raise APIError(
            503, "data_view_busy", "Report data viewers are busy; try again"
        ) from None
    deadline = time.monotonic() + deps.settings(request).download_timeout
    try:
        payload, filename = await run_in_threadpool(
            _prepare, request, report_id, kind, index, deadline
        )
        headers = {
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        }
        if kind != "catalog":
            headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return InputResponse(
            payload,
            request=request,
            borrower=borrower,
            deadline=deadline,
            media_type="application/json"
            if kind == "catalog"
            else "application/zip"
            if kind == "zip"
            else "application/octet-stream",
            headers=headers,
        )
    except BaseException:
        limiter.release_on_behalf_of(borrower)
        raise


@router.get("/{report_id}/files")
async def files(report_id: UUID, request: Request) -> Response:
    return await read_input(request, report_id, "catalog")


@router.get("/{report_id}/files/{index}/content")
async def content(report_id: UUID, index: int, request: Request) -> Response:
    return await read_input(request, report_id, "file", index)


@router.get("/{report_id}/input")
async def raw_input(report_id: UUID, request: Request) -> Response:
    return await read_input(request, report_id, "raw")


@router.get("/{report_id}/inputs.zip")
async def inputs_zip(report_id: UUID, request: Request) -> Response:
    return await read_input(request, report_id, "zip")
