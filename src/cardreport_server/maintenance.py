"""Bounded, retryable expiry and orphan collection using database time."""

from datetime import timedelta
from typing import TYPE_CHECKING

from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from mypy_boto3_s3.type_defs import ListObjectsV2RequestTypeDef

from .db import Database
from .settings import Settings
from .storage import Storage


def maintain(db: Database, storage: Storage, settings: Settings) -> None:
    with db.pool.connection() as conn:
        conn.execute(
            """WITH old AS (
            SELECT id FROM reports WHERE state='queued' AND created_at<clock_timestamp()-(%s*interval '1 second')
            FOR UPDATE SKIP LOCKED LIMIT %s
        ) UPDATE reports r SET state='failed',terminal_state='failed',finished_at=clock_timestamp(),
            error='{"code":"queue_expired","stage":"queue","message":"Maximum queue age exceeded","retryable":false}'::jsonb,
            input_expires_at=clock_timestamp()+input_retention*interval '1 second',
            metadata_expires_at=clock_timestamp()+metadata_retention*interval '1 second'
            FROM old WHERE r.id=old.id""",
            (settings.queue_max_age, settings.maintenance_batch_size),
        )
        conn.execute(
            "UPDATE reports SET state='expired' WHERE (state='succeeded' AND result_expires_at<=clock_timestamp()) OR (state='failed' AND input_expires_at<=clock_timestamp())"
        )
        rows = conn.execute(
            """SELECT id,input_key,result_key,
            NOT input_deleted AND input_expires_at<=clock_timestamp() AS remove_input,
            NOT result_deleted AND result_expires_at<=clock_timestamp()-(%s*interval '1 second') AS remove_result
            FROM reports WHERE (NOT input_deleted AND input_expires_at<=clock_timestamp())
            OR (NOT result_deleted AND result_expires_at<=clock_timestamp()-(%s*interval '1 second'))
            ORDER BY finished_at LIMIT %s""",
            (
                settings.download_timeout,
                settings.download_timeout,
                settings.maintenance_batch_size,
            ),
        ).fetchall()
    for row in rows:
        for role in ("input", "result"):
            if row["remove_" + role] and row[role + "_key"]:
                storage.delete(row[role + "_key"])
                with db.pool.connection() as conn:
                    # Column names are closed constants, never request values.
                    conn.execute(
                        f"UPDATE reports SET {role}_deleted=true WHERE id=%s",
                        (row["id"],),
                    )
    with db.pool.connection() as conn:
        conn.execute(
            """DELETE FROM reports WHERE id IN (
            SELECT id FROM reports WHERE metadata_expires_at<=clock_timestamp() AND input_deleted
            AND (result_key IS NULL OR result_deleted) LIMIT %s)""",
            (settings.maintenance_batch_size,),
        )


class OrphanSweep:
    """One bounded S3 page per tick; a new sweep starts after the last page."""

    def __init__(self) -> None:
        self.cursor: str | None = None

    def run(self, db: Database, storage: Storage, settings: Settings) -> None:
        with db.pool.connection() as conn:
            row = conn.execute("SELECT clock_timestamp() AS now").fetchone()
        assert row is not None
        cutoff = row["now"] - timedelta(seconds=settings.orphan_grace)
        params: ListObjectsV2RequestTypeDef = {
            "Bucket": storage.bucket,
            "Prefix": storage.prefix,
            "MaxKeys": settings.maintenance_batch_size,
        }
        if self.cursor:
            params["ContinuationToken"] = self.cursor
        try:
            page = storage.client.list_objects_v2(**params)
        except ClientError:
            self.cursor = None
            raise
        for item in page.get("Contents", []):
            key = item["Key"]
            if item["LastModified"] >= cutoff or not key.startswith(
                (storage.prefix + "inputs/", storage.prefix + "results/")
            ):
                continue
            with db.pool.connection() as conn:
                referenced = conn.execute(
                    "SELECT 1 FROM reports WHERE input_key=%s OR result_key=%s LIMIT 1",
                    (key, key),
                ).fetchone()
            if referenced is None:
                storage.delete(key)
        self.cursor = page.get("NextContinuationToken")
