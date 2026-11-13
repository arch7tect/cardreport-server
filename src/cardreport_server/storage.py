"""The small S3 operation set used by the service."""

import hashlib
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

import boto3
from botocore.config import Config
from botocore.response import StreamingBody

from .settings import Settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


class Storage:
    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.s3_bucket
        self.prefix = settings.s3_prefix
        self.client: S3Client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key.get_secret_value(),
            aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
            region_name=settings.s3_region,
            config=Config(
                connect_timeout=settings.io_timeout,
                read_timeout=settings.io_timeout,
                retries={"total_max_attempts": 2},
                s3={"addressing_style": "path"},
            ),
        )

    def check(self) -> None:
        self.client.head_bucket(Bucket=self.bucket)

    def put(self, key: str, path: Path, content_type: str) -> None:
        with path.open("rb") as stream:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=stream,
                ContentLength=path.stat().st_size,
                ContentType=content_type,
            )

    def get(self, key: str) -> StreamingBody:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"]

    def download(self, key: str, destination: BinaryIO, limit: int) -> int:
        body = self.get(key)
        total = 0
        try:
            for chunk in body.iter_chunks(64 * 1024):
                total += len(chunk)
                if total > limit:
                    raise ValueError("Stored object exceeds its size limit")
                destination.write(chunk)
        finally:
            body.close()
        return total

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def objects(self) -> Iterator[tuple[str, datetime]]:
        pages = self.client.get_paginator("list_objects_v2")
        for page in pages.paginate(
            Bucket=self.bucket, Prefix=self.prefix, PaginationConfig={"PageSize": 100}
        ):
            for item in page.get("Contents", []):
                yield item["Key"], item["LastModified"]


def read_verified(
    body: StreamingBody,
    size: int,
    expected_hash: str,
    deadline: float,
    *,
    integrity: Exception,
    timeout: Exception,
) -> bytes:
    """Read at most the declared size, verify it and always close the object body."""
    raw = bytearray()
    digest = hashlib.sha256()
    try:
        while True:
            if time.monotonic() >= deadline:
                raise timeout
            chunk = body.read(min(64 * 1024, size + 1 - len(raw)))
            if not chunk:
                break
            if len(raw) + len(chunk) > size:
                raise integrity
            raw.extend(chunk)
            digest.update(chunk)
    finally:
        body.close()
    if len(raw) != size or digest.hexdigest() != expected_hash:
        raise integrity
    return bytes(raw)
