"""Bounded downloads; headers are sent only for committed, unexpired results."""

from collections.abc import AsyncIterator
from typing import Literal
from uuid import UUID

import anyio
from botocore.response import StreamingBody
from fastapi import Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from .db import Database
from .errors import APIError


class DownloadResponse(StreamingResponse):
    def __init__(self, body: StreamingBody, timeout: float, **kwargs: object) -> None:
        self.object_body = body
        self.timeout = timeout

        async def chunks() -> AsyncIterator[bytes]:
            while chunk := await run_in_threadpool(body.read, 64 * 1024):
                yield chunk

        super().__init__(chunks(), **kwargs)  # type: ignore[arg-type]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            with anyio.fail_after(self.timeout):
                await super().__call__(scope, receive, send)
        finally:
            self.object_body.close()


def artifact_row(
    db: Database, report_id: UUID, artifact: Literal["result", "data"] = "result"
) -> dict[str, object]:
    with db.pool.connection() as conn:
        row = conn.execute(
            """SELECT state,result_key,result_size,result_hash,data_key,data_size,data_hash,output_kind,
            result_expires_at>clock_timestamp() AS available FROM reports WHERE id=%s""",
            (report_id,),
        ).fetchone()
    if row is None:
        raise APIError(404, "report_not_found", "Report does not exist")
    if row["state"] == "expired" or (
        row["state"] == "succeeded" and not row["available"]
    ):
        raise APIError(410, "result_expired", "Report result expired")
    if row["state"] != "succeeded":
        raise APIError(409, "result_not_ready", "No successful report result available")
    if artifact == "data" and row["data_key"] is None:
        raise APIError(
            404, "data_unavailable", "This report has no saved dataset snapshot"
        )
    return row


async def download(
    report_id: UUID,
    request: Request,
    disposition: Literal["attachment", "inline"] = "attachment",
    *,
    artifact: Literal["result", "data"] = "result",
) -> DownloadResponse:
    db: Database = request.app.state.database

    def lookup() -> dict[str, object]:
        return artifact_row(db, report_id, artifact)

    row = await run_in_threadpool(lookup)
    policy = (
        "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
        "font-src data:; script-src 'unsafe-inline'"
    )
    if disposition == "inline" and row["output_kind"] == "html":
        policy = (
            "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; "
            "style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
        )
    elif disposition == "inline":
        # Native PDF viewers have their own isolation; CSP sandbox prevents them loading.
        policy = "default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    body = await run_in_threadpool(
        request.app.state.storage.get, row[artifact + "_key"]
    )
    try:
        # Recheck after object open, before headers; collection allows a full download grace.
        await run_in_threadpool(lookup)
        output = "json" if artifact == "data" else row["output_kind"]
        return DownloadResponse(
            body,
            request.app.state.settings.download_timeout,
            media_type={
                "pdf": "application/pdf",
                "html": "text/html",
                "json": "application/json",
            }[str(output)],
            headers={
                "Content-Disposition": f'{disposition}; filename="report-{report_id}.{output}"',
                "Content-Length": str(row[artifact + "_size"]),
                "ETag": '"' + str(row[artifact + "_hash"]) + '"',
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": policy,
            },
        )
    except BaseException:
        body.close()
        raise
