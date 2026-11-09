"""HTTP application; resource routes are added independently of rendering."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from psycopg import InterfaceError, OperationalError
from psycopg_pool import PoolTimeout
from starlette.concurrency import run_in_threadpool

from .db import Database
from .errors import APIError
from .middleware import SafeErrors
from .openapi import install_schemas
from .reports import router as reports_router
from .settings import Settings
from .storage import Storage
from .templates import router as templates_router
from .ui import ConsoleFiles


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    database = Database(config)
    storage = Storage(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            await run_in_threadpool(database.open)
            await run_in_threadpool(storage.check)
            yield
        finally:
            database.close()

    app = FastAPI(
        title="CardReport Server",
        version="0.1.0.dev0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    app.add_middleware(SafeErrors)
    app.state.data_view_limiter = anyio.CapacityLimiter(config.data_view_slots)
    app.state.upload_limiter = anyio.CapacityLimiter(config.upload_slots)
    app.state.settings = config
    app.state.database = database
    app.state.storage = storage

    @app.get("/health/live", include_in_schema=False)
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", include_in_schema=False)
    def ready() -> JSONResponse:
        try:
            database.check()
            storage.check()
        except Exception:
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return JSONResponse({"status": "ok"})

    @app.exception_handler(APIError)
    async def api_error(request: Request, error: APIError) -> JSONResponse:
        return JSONResponse(
            error.body(),
            status_code=error.status,
            headers={"Retry-After": "5"} if error.status in {429, 503} else None,
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            {
                "error": {
                    "code": "invalid_request",
                    "message": "Invalid request parameters",
                }
            },
            status_code=422,
        )

    async def unavailable(request: Request, error: Exception) -> JSONResponse:
        return JSONResponse(
            {
                "error": {
                    "code": "dependency_unavailable",
                    "message": "Service dependency unavailable",
                }
            },
            status_code=503,
        )

    for error_type in (
        OperationalError,
        InterfaceError,
        PoolTimeout,
        BotoCoreError,
        ClientError,
    ):
        app.add_exception_handler(error_type, unavailable)

    app.mount(
        "/ui",
        ConsoleFiles(directory=Path(__file__).parent / "web", html=True),
        name="console",
    )
    app.mount(
        "/static",
        StaticFiles(directory=Path(__file__).parent / "static"),
        name="static",
    )

    @app.get("/docs", include_in_schema=False)
    def docs() -> HTMLResponse:
        return get_swagger_ui_html(
            openapi_url="/openapi.json",
            title="CardReport API",
            swagger_js_url="/static/swagger-ui-bundle.js",
            swagger_css_url="/static/swagger-ui.css",
            swagger_favicon_url="/static/favicon-32x32.png",
            swagger_ui_parameters={"validatorUrl": None},
        )

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        from .metrics import queue_metrics

        return Response(queue_metrics(database), media_type="text/plain; version=0.0.4")

    app.include_router(templates_router)
    app.include_router(reports_router)
    install_schemas(app)
    return app
