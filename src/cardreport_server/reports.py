"""Stream dataset bundles into durable, independently rendered jobs."""

import hashlib
import tempfile
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

import anyio
from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from . import dependencies as deps
from . import history, jobs
from .errors import APIError
from .intake import media_type
from .openapi import request_schema
from .templates import ensure_admission

router = APIRouter(prefix="/v1/reports", tags=["Reports"])
_CONTENT_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"content": {"application/pdf": {}, "text/html": {}}}
}
_DATA_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"content": {"application/json": {}}}
}


@router.post("", status_code=202, openapi_extra=request_schema("data"))
async def submit(
    request: Request,
    template_id: Annotated[str, Query(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")],
    template_version: Annotated[int | None, Query(ge=1)] = None,
    output: jobs.Output = "pdf",
    renderer: jobs.RendererName = "chromium",
) -> JSONResponse:
    ensure_admission(request)
    settings = deps.settings(request)
    db = deps.database(request)
    storage = deps.storage(request)
    kind = media_type(request, settings.input_limit, multipart=True)
    limiter = deps.upload_limiter(request)
    with deps.slot(
        limiter, APIError(429, "uploads_busy", "All upload slots are occupied")
    ):
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
                        renderer,
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
                "renderer": renderer,
                "status_url": location,
                "content_url": location + "/content",
            },
            status_code=202,
            headers={"Location": location},
        )


@router.get("")
def report_history(
    request: Request,
    template_id: Annotated[
        str | None, Query(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    ] = None,
    state: history.State | None = None,
    after: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    created_from: Annotated[
        AwareDatetime | None,
        Query(description="Creation time, inclusive; ISO 8601 with timezone"),
    ] = None,
    created_before: Annotated[
        AwareDatetime | None,
        Query(description="Creation time, exclusive; ISO 8601 with timezone"),
    ] = None,
) -> dict[str, Any]:
    return history.list_reports(
        deps.database(request),
        template_id=template_id,
        state=state,
        after=after,
        limit=limit,
        created_from=created_from,
        created_before=created_before,
    )


@router.get("/{report_id}")
def report_status(report_id: UUID, request: Request) -> dict[str, Any]:
    return jobs.status(deps.database(request), report_id)


@router.get(
    "/{report_id}/content",
    responses=_CONTENT_RESPONSES,
)
async def report_content(
    report_id: UUID,
    request: Request,
    disposition: Literal["attachment", "inline"] = "attachment",
) -> Any:
    from .downloads import download

    return await download(report_id, request, disposition)


@router.get("/{report_id}/data", responses=_DATA_RESPONSES)
async def report_data(report_id: UUID, request: Request) -> Any:
    from .downloads import download

    return await download(report_id, request, artifact="data")


@router.get("/{report_id}/datasets")
async def report_datasets(
    report_id: UUID, request: Request, response: Response
) -> dict[str, Any]:
    from .data_view import read_snapshot

    response.headers["Cache-Control"] = "no-store"
    datasets = await read_snapshot(request, report_id)
    return {
        "items": [
            {"name": name, "columns": dataset.columns, "row_count": len(dataset.rows)}
            for name, dataset in datasets.items()
        ]
    }


@router.get("/{report_id}/dataset")
async def report_dataset(
    report_id: UUID,
    name: str,
    request: Request,
    response: Response,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> dict[str, Any]:
    from .data_view import display_cell, read_snapshot

    response.headers["Cache-Control"] = "no-store"
    datasets = await read_snapshot(request, report_id)
    if name not in datasets:
        raise APIError(
            404, "dataset_not_found", "Dataset does not exist in this report"
        )
    dataset = datasets[name]
    return {
        "name": name,
        "columns": dataset.columns,
        "row_count": len(dataset.rows),
        "offset": offset,
        "rows": [
            [display_cell(value) for value in row]
            for row in dataset.rows[offset : offset + limit]
        ],
    }
