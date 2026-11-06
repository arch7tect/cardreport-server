"""Contain unexpected errors before the ASGI server can log their payloads."""

import logging
from uuid import uuid4

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class SafeErrors:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracked_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracked_send)
        except Exception as error:
            correlation_id = uuid4().hex
            logging.getLogger(__name__).error(
                "Internal error %s (%s)", correlation_id, type(error).__name__
            )
            if not started:
                response = JSONResponse(
                    {
                        "error": {
                            "code": "internal_error",
                            "message": "Internal service error",
                            "id": correlation_id,
                        }
                    },
                    status_code=500,
                )
                await response(scope, receive, send)
            # A partially streamed response stays incomplete, causing server connection closure.
            # Do not re-raise an exception whose message may contain report data.
