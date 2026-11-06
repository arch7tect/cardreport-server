"""Stream dataset bundles into durable, independently rendered jobs."""

import hashlib
import tempfile
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID, uuid4

import anyio
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from . import jobs
from .errors import APIError
from .intake import media_type
from .openapi import request_schema
from .templates import ensure_admission

router = APIRouter(prefix="/v1/reports", tags=["Reports"])


@router.post("", status_code=202, openapi_extra=request_schema("data"))
async def submit(
    request: Request,
    template_id: Annotated[str, Query(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")],
    template_version: Annotated[int | None, Query(ge=1)] = None,
    output: jobs.Output = "pdf",
) -> JSONResponse:
    ensure_admission(request)
    settings = request.app.state.settings
    db = request.app.state.database
    storage = request.app.state.storage
    kind = media_type(request, settings.input_limit)
    limiter = request.app.state.upload_limiter
    try:
        limiter.acquire_nowait()
    except anyio.WouldBlock:
        raise APIError(429, "uploads_busy", "All upload slots are occupied") from None
    try:
        admission = await run_in_threadpool(
            jobs.admit, db, settings, template_id, template_version
        )
        report_id = uuid4()
        key = storage.prefix + "inputs/" + str(report_id)
        digest = hashlib.sha256()
        total = 0
        with tempfile.TemporaryDirectory(prefix="cardreport-upload-") as directory:
            path = Path(directory) / "data"
            try:
                with anyio.fail_after(settings.upload_timeout):
                    with path.open("wb") as stream:
                        iterator = request.stream().__aiter__()
                        while True:
                            try:
                                with anyio.fail_after(settings.upload_idle_timeout):
                                    chunk = await anext(iterator)
                            except StopAsyncIteration:
                                break
                            total += len(chunk)
                            if total > settings.input_limit:
                                raise APIError(
                                    413,
                                    "input_too_large",
                                    "Dataset bundle exceeds its size limit",
                                )
                            digest.update(chunk)
                            await run_in_threadpool(stream.write, chunk)
                    await run_in_threadpool(storage.put, key, path, kind)
                    await run_in_threadpool(
                        jobs.enqueue,
                        db,
                        settings,
                        admission,
                        report_id,
                        key,
                        kind,
                        total,
                        digest.hexdigest(),
                        output,
                    )
            except TimeoutError:
                raise APIError(
                    408, "upload_timeout", "Dataset upload timed out"
                ) from None
            except ClientDisconnect:
                raise APIError(
                    400, "upload_interrupted", "Dataset upload interrupted"
                ) from None
        location = f"/v1/reports/{report_id}"
        return JSONResponse(
            {
                "id": str(report_id),
                "state": "queued",
                "template_id": template_id,
                "template_version": admission.template_version,
                "output": output,
                "status_url": location,
                "content_url": location + "/content",
            },
            status_code=202,
            headers={"Location": location},
        )
    finally:
        limiter.release()


@router.get("/{report_id}")
def report_status(report_id: UUID, request: Request) -> dict[str, Any]:
    return jobs.status(request.app.state.database, report_id)


@router.get(
    "/{report_id}/content",
    responses={200: {"content": {"application/pdf": {}, "text/html": {}}}},
)
async def report_content(report_id: UUID, request: Request) -> Any:
    from .downloads import download

    return await download(report_id, request)
