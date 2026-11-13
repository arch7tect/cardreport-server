"""Typed access to resources owned by the application lifespan."""

from collections.abc import Iterator
from contextlib import contextmanager

import anyio
from fastapi import Request

from .db import Database
from .errors import APIError
from .settings import Settings
from .storage import Storage


def settings(request: Request) -> Settings:
    value: Settings = request.app.state.settings
    return value


def database(request: Request) -> Database:
    value: Database = request.app.state.database
    return value


def storage(request: Request) -> Storage:
    value: Storage = request.app.state.storage
    return value


def upload_limiter(request: Request) -> anyio.CapacityLimiter:
    value: anyio.CapacityLimiter = request.app.state.upload_limiter
    return value


def data_view_limiter(request: Request) -> anyio.CapacityLimiter:
    value: anyio.CapacityLimiter = request.app.state.data_view_limiter
    return value


@contextmanager
def slot(limiter: anyio.CapacityLimiter, busy: APIError) -> Iterator[None]:
    try:
        limiter.acquire_nowait()
    except anyio.WouldBlock:
        raise busy from None
    try:
        yield
    finally:
        limiter.release()
