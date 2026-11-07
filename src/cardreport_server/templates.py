"""Immutable template revisions with short, serialized writer transactions."""

import hashlib
from importlib.metadata import version
from typing import Annotated, Any

import anyio
from cardreport import Page as ReportPage
from cardreport import ReportTemplate, TemplateError
from fastapi import APIRouter, Path, Query, Request
from psycopg.types.json import Json
from pydantic import BaseModel, ConfigDict
from starlette.concurrency import run_in_threadpool

from .db import Database
from .errors import APIError
from .intake import read_template
from .openapi import request_schema

router = APIRouter(prefix="/v1/templates", tags=["Templates"])
Slug = Annotated[str, Path(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]


def ensure_admission(request: Request) -> None:
    if not request.app.state.settings.admission_enabled:
        raise APIError(503, "admission_paused", "New work is temporarily paused")


def register(db: Database, template_id: str, body: bytes, kind: str) -> dict[str, Any]:
    try:
        template = (
            ReportTemplate.from_json(body)
            if kind == "application/json"
            else ReportTemplate.from_yaml(body)
        )
    except TemplateError as error:
        location = {"template_path": error.template_path} if error.template_path else {}
        raise APIError(
            422, "invalid_template", "Template validation failed", location=location
        ) from None
    definition = template.to_dict()
    digest = hashlib.sha256(template.to_json().encode()).hexdigest()
    with db.pool.connection() as conn:
        conn.execute(
            "INSERT INTO templates(id) VALUES (%s) ON CONFLICT DO NOTHING",
            (template_id,),
        )
        row = conn.execute(
            "SELECT * FROM templates WHERE id=%s FOR UPDATE", (template_id,)
        ).fetchone()
        assert row is not None
        if row["archived"]:
            raise APIError(409, "template_archived", "Template is archived")
        revision = int(row["latest_version"]) + 1
        created = conn.execute(
            "INSERT INTO template_versions(template_id,version,definition,digest,validated_with) "
            "VALUES (%s,%s,%s,%s,%s) RETURNING template_id,version,digest,validated_with,created_at",
            (
                template_id,
                revision,
                Json(definition, dumps=lambda value: template.to_json()),
                digest,
                version("cardreport"),
            ),
        ).fetchone()
        conn.execute(
            "UPDATE templates SET latest_version=%s WHERE id=%s",
            (revision, template_id),
        )
        assert created is not None
        return created


@router.post(
    "/{template_id}/versions", status_code=201, openapi_extra=request_schema("template")
)
async def create_version(template_id: Slug, request: Request) -> dict[str, Any]:
    ensure_admission(request)
    limiter = request.app.state.upload_limiter
    try:
        limiter.acquire_nowait()
    except anyio.WouldBlock:
        raise APIError(429, "uploads_busy", "All upload slots are occupied") from None
    try:
        body, kind = await read_template(request)
        return await run_in_threadpool(
            register, request.app.state.database, template_id, body, kind
        )
    finally:
        limiter.release()


@router.get("")
def list_templates(
    request: Request,
    archived: bool | None = None,
    after: Annotated[str, Query(max_length=64)] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    with request.app.state.database.pool.connection() as conn:
        rows = conn.execute(
            "SELECT * FROM templates WHERE id>%s AND "
            "(%s::boolean IS NULL OR archived=%s) ORDER BY id LIMIT %s",
            (after, archived, archived, limit + 1),
        ).fetchall()
    return {
        "items": rows[:limit],
        "next": rows[limit - 1]["id"] if len(rows) > limit else None,
    }


@router.get("/{template_id}")
def get_template(template_id: Slug, request: Request) -> dict[str, Any]:
    with request.app.state.database.pool.connection() as conn:
        row = conn.execute(
            "SELECT * FROM templates WHERE id=%s", (template_id,)
        ).fetchone()
    if row is None:
        raise APIError(404, "template_not_found", "Template does not exist")
    return dict(row)


@router.get("/{template_id}/versions")
def list_versions(
    template_id: Slug,
    request: Request,
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    get_template(template_id, request)
    with request.app.state.database.pool.connection() as conn:
        rows = conn.execute(
            "SELECT template_id,version,digest,validated_with,created_at "
            "FROM template_versions WHERE template_id=%s AND version>%s "
            "ORDER BY version LIMIT %s",
            (template_id, after, limit + 1),
        ).fetchall()
    return {
        "items": rows[:limit],
        "next": rows[limit - 1]["version"] if len(rows) > limit else None,
    }


@router.get("/{template_id}/versions/{revision}")
def get_version(
    template_id: Slug, revision: Annotated[int, Path(ge=1)], request: Request
) -> dict[str, Any]:
    with request.app.state.database.pool.connection() as conn:
        row = conn.execute(
            "SELECT * FROM template_versions WHERE template_id=%s AND version=%s",
            (template_id, revision),
        ).fetchone()
    if row is None:
        raise APIError(404, "template_not_found", "Template version does not exist")
    return {
        **row,
        "page_dimensions_mm": ReportPage(
            **row["definition"]["report"].get("page", {})
        ).dimensions(),
    }


class ArchiveChange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    archived: bool


@router.patch("/{template_id}")
def archive(
    template_id: Slug, change: ArchiveChange, request: Request
) -> dict[str, Any]:
    ensure_admission(request)
    with request.app.state.database.pool.connection() as conn:
        row = conn.execute(
            "UPDATE templates SET archived=%s WHERE id=%s RETURNING *",
            (change.archived, template_id),
        ).fetchone()
    if row is None:
        raise APIError(404, "template_not_found", "Template does not exist")
    return dict(row)
