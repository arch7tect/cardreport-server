"""Durable report admission, PostgreSQL queue and attempt ownership."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import ceil
from typing import Any
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.sql import SQL
from psycopg.types.json import Jsonb

from .db import Database
from .errors import APIError
from .history import STATUS_COLUMNS
from .render_contract import Artifact, Outcome
from .render_contract import Output as Output
from .render_contract import RendererName as RendererName
from .settings import Settings


@dataclass(frozen=True)
class Admission:
    template_id: str
    template_version: int
    deadline: datetime
    retention: int
    metadata_retention: int


def _check_backlog(conn: Connection[dict[str, Any]], limit: int) -> None:
    count = conn.execute(
        "SELECT count(*) AS n FROM reports WHERE state IN ('queued','running')"
    ).fetchone()
    assert count is not None
    if count["n"] >= limit:
        raise APIError(429, "queue_full", "Report queue is at capacity")


def admit(
    db: Database, settings: Settings, template_id: str, revision: int | None
) -> Admission:
    with db.pool.connection() as conn:
        row = conn.execute(
            "SELECT archived,latest_version,retention_seconds,clock_timestamp() AS admitted_at "
            "FROM templates WHERE id=%s",
            (template_id,),
        ).fetchone()
        if row is None:
            raise APIError(404, "template_not_found", "Template does not exist")
        if row["archived"]:
            raise APIError(409, "template_archived", "Template is archived")
        chosen = revision if revision is not None else int(row["latest_version"])
        if (
            conn.execute(
                "SELECT 1 FROM template_versions WHERE template_id=%s AND version=%s",
                (template_id, chosen),
            ).fetchone()
            is None
        ):
            raise APIError(404, "template_not_found", "Template version does not exist")
        _check_backlog(conn, settings.backlog_limit)
        retention = row["retention_seconds"] or settings.result_retention
        return Admission(
            template_id,
            chosen,
            row["admitted_at"] + timedelta(seconds=settings.upload_timeout),
            retention,
            max(
                settings.metadata_retention,
                retention + ceil(settings.download_timeout) + 1,
            ),
        )


def enqueue(
    db: Database,
    settings: Settings,
    admission: Admission,
    report_id: UUID,
    input_key: str,
    input_type: str,
    input_size: int,
    input_hash: str,
    output: Output,
    renderer: RendererName = "chromium",
) -> None:
    with db.pool.connection() as conn:
        _check_backlog(conn, settings.backlog_limit)
        result = conn.execute(
            """
            INSERT INTO reports(id,template_id,template_version,input_key,input_type,input_size,input_hash,
                                output_kind,renderer,input_retention,result_retention,metadata_retention)
            SELECT %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s WHERE clock_timestamp() < %s RETURNING id
            """,
            (
                report_id,
                admission.template_id,
                admission.template_version,
                input_key,
                input_type,
                input_size,
                input_hash,
                output,
                renderer,
                admission.retention,
                admission.retention,
                admission.metadata_retention,
                admission.deadline,
            ),
        ).fetchone()
        if result is None:
            raise APIError(408, "upload_timeout", "Upload acceptance deadline expired")


def status(db: Database, report_id: UUID) -> dict[str, Any]:
    with db.pool.connection() as conn:
        row = conn.execute(
            SQL("SELECT {} FROM reports WHERE id=%s").format(STATUS_COLUMNS),
            (report_id,),
        ).fetchone()
    if row is None:
        raise APIError(404, "report_not_found", "Report does not exist")
    return row


@dataclass(frozen=True)
class Attempt:
    report_id: UUID
    token: UUID
    attempt_no: int
    template_id: str
    template_version: int
    input_key: str
    input_type: str
    input_size: int
    input_hash: str
    output: Output
    renderer: RendererName
    lease_until: datetime
    deadline: datetime


def claim(db: Database, settings: Settings) -> Attempt | None:
    token = uuid4()
    with db.pool.connection() as conn:
        row = conn.execute(
            """
            WITH candidate AS (
                SELECT id FROM reports WHERE state='queued' AND next_attempt_at<=clock_timestamp()
                ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT 1
            )
            UPDATE reports r SET state='running',attempt_no=attempt_no+1,attempt_token=%s,
                lease_until=clock_timestamp()+(%s*interval '1 second'),
                attempt_deadline=clock_timestamp()+(%s*interval '1 second'),
                started_at=COALESCE(started_at,clock_timestamp())
            FROM candidate c WHERE r.id=c.id RETURNING r.*
            """,
            (token, settings.lease_seconds, settings.attempt_timeout),
        ).fetchone()
    if row is None:
        return None
    return Attempt(
        report_id=row["id"],
        token=token,
        attempt_no=row["attempt_no"],
        template_id=row["template_id"],
        template_version=row["template_version"],
        input_key=row["input_key"],
        input_type=row["input_type"],
        input_size=row["input_size"],
        input_hash=row["input_hash"],
        output=row["output_kind"],
        renderer=row["renderer"],
        lease_until=row["lease_until"],
        deadline=row["attempt_deadline"],
    )


def heartbeat(db: Database, settings: Settings, attempts: list[Attempt]) -> set[UUID]:
    if not attempts:
        return set()
    with db.pool.connection() as conn:
        rows = conn.execute(
            """UPDATE reports SET lease_until=LEAST(attempt_deadline,
            clock_timestamp()+(%s*interval '1 second'))
            WHERE state='running' AND attempt_token=ANY(%s) AND lease_until>clock_timestamp()
            AND attempt_deadline>clock_timestamp() RETURNING attempt_token""",
            (settings.lease_seconds, [a.token for a in attempts]),
        ).fetchall()
    return {row["attempt_token"] for row in rows}


def finish(
    db: Database,
    attempt: Attempt,
    *,
    result: Artifact | None = None,
    error: Outcome | None = None,
    data: Artifact | None = None,
    files: list[dict[str, Any]] | None = None,
    engine_version: str,
    image_id: str,
    service_version: str,
) -> bool:
    succeeded = result is not None
    state = "succeeded" if succeeded else "failed"
    result_values: Mapping[str, object] = result or {}
    data_values: Mapping[str, object] = data or {}
    with db.pool.connection() as conn:
        row = conn.execute(
            """UPDATE reports SET state=%s,terminal_state=%s,finished_at=clock_timestamp(),
            result_key=%s,result_size=%s,result_hash=%s,data_key=%s,data_size=%s,data_hash=%s,error=%s,input_files=%s,
            input_expires_at=clock_timestamp()+input_retention*interval '1 second',
            result_expires_at=CASE WHEN %s THEN clock_timestamp()+result_retention*interval '1 second' END,
            metadata_expires_at=clock_timestamp()+metadata_retention*interval '1 second',
            engine_version=%s,image_id=%s,service_version=%s,lease_until=NULL
            WHERE id=%s AND attempt_token=%s AND state='running' AND lease_until>clock_timestamp()
            AND attempt_deadline>clock_timestamp() RETURNING id""",
            (
                state,
                state,
                result_values.get("key"),
                result_values.get("size"),
                result_values.get("hash"),
                data_values.get("key"),
                data_values.get("size"),
                data_values.get("hash"),
                Jsonb(error) if error else None,
                Jsonb(files) if files is not None else None,
                succeeded,
                engine_version,
                image_id,
                service_version,
                attempt.report_id,
                attempt.token,
            ),
        ).fetchone()
    return row is not None


def retry(
    db: Database,
    settings: Settings,
    attempt: Attempt,
    code: str = "dependency_unavailable",
) -> bool:
    with db.pool.connection() as conn:
        row = conn.execute(
            """UPDATE reports SET
            state=CASE WHEN (attempt_no >= %s OR attempt_deadline<=clock_timestamp()) THEN 'failed' ELSE 'queued' END,
            terminal_state=CASE WHEN (attempt_no >= %s OR attempt_deadline<=clock_timestamp()) THEN 'failed' END,
            finished_at=CASE WHEN (attempt_no >= %s OR attempt_deadline<=clock_timestamp()) THEN clock_timestamp() END,
            input_expires_at=CASE WHEN (attempt_no >= %s OR attempt_deadline<=clock_timestamp()) THEN clock_timestamp()+input_retention*interval '1 second' END,
            metadata_expires_at=CASE WHEN (attempt_no >= %s OR attempt_deadline<=clock_timestamp()) THEN clock_timestamp()+metadata_retention*interval '1 second' END,
            error=CASE WHEN attempt_deadline<=clock_timestamp() THEN '{"code":"render_timeout","stage":"render","message":"Execution deadline expired","retryable":false}'::jsonb ELSE %s END,lease_until=NULL,
            next_attempt_at=clock_timestamp()+(%s*interval '1 second')
            WHERE id=%s AND attempt_token=%s AND state='running' AND lease_until>clock_timestamp()
            RETURNING id""",
            (settings.max_attempts,) * 5
            + (
                Jsonb(
                    {
                        "code": code,
                        "stage": "infrastructure",
                        "message": "Report execution interrupted",
                        "retryable": attempt.attempt_no < settings.max_attempts,
                    }
                ),
                min(
                    settings.retry_delay * 2 ** (attempt.attempt_no - 1),
                    settings.retry_max_delay,
                ),
                attempt.report_id,
                attempt.token,
            ),
        ).fetchone()
    return row is not None


def reap(db: Database, settings: Settings) -> int:
    with db.pool.connection() as conn:
        rows = conn.execute(
            """WITH expired AS (
                SELECT id FROM reports WHERE state='running' AND lease_until<=clock_timestamp()
                ORDER BY lease_until FOR UPDATE SKIP LOCKED LIMIT %s
            ) UPDATE reports r SET state=CASE WHEN (attempt_no >= %s OR attempt_deadline<=clock_timestamp()) THEN 'failed' ELSE 'queued' END,
                terminal_state=CASE WHEN (attempt_no >= %s OR attempt_deadline<=clock_timestamp()) THEN 'failed' END,
                finished_at=CASE WHEN (attempt_no >= %s OR attempt_deadline<=clock_timestamp()) THEN clock_timestamp() END,
                input_expires_at=CASE WHEN (attempt_no >= %s OR attempt_deadline<=clock_timestamp()) THEN clock_timestamp()+input_retention*interval '1 second' END,
                metadata_expires_at=CASE WHEN (attempt_no >= %s OR attempt_deadline<=clock_timestamp()) THEN clock_timestamp()+metadata_retention*interval '1 second' END,
                lease_until=NULL,next_attempt_at=clock_timestamp()+(LEAST(%s*power(2,attempt_no-1),%s)*interval '1 second'),
                error=jsonb_build_object('code',CASE WHEN attempt_deadline<=clock_timestamp() THEN 'render_timeout' ELSE 'worker_lost' END,
                    'stage',CASE WHEN attempt_deadline<=clock_timestamp() THEN 'render' ELSE 'infrastructure' END,
                    'message','Worker ownership expired','retryable', (attempt_no < %s AND attempt_deadline>clock_timestamp()))
            FROM expired e WHERE r.id=e.id RETURNING r.id""",
            (settings.maintenance_batch_size,)
            + (settings.max_attempts,) * 5
            + (settings.retry_delay, settings.retry_max_delay, settings.max_attempts),
        ).fetchall()
    return len(rows)
