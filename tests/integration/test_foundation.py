import io
from pathlib import Path
from uuid import uuid4

import boto3
import pytest
from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import ClientError

from cardreport_server.db import Database
from cardreport_server.settings import Settings
from cardreport_server.storage import Storage

pytestmark = pytest.mark.integration


def test_revision(database: Database) -> None:
    database.check()


def test_storage_round_trip(storage: Storage, tmp_path: Path) -> None:
    prefix = storage.prefix + str(uuid4()) + "/"
    path = tmp_path / "input"
    path.write_bytes(b"report-data\x00" * 1000)
    keys = [prefix + str(i) for i in range(3)]
    try:
        for key in keys:
            storage.put(key, path, "application/octet-stream")
        body = io.BytesIO()
        assert storage.download(keys[0], body, 20000) == path.stat().st_size
        assert body.getvalue() == path.read_bytes()
        assert (
            storage.client.head_object(Bucket=storage.bucket, Key=keys[0])[
                "ContentLength"
            ]
            == path.stat().st_size
        )
        pages = list(
            storage.client.get_paginator("list_objects_v2").paginate(
                Bucket=storage.bucket, Prefix=prefix, PaginationConfig={"PageSize": 1}
            )
        )
        assert len(pages) == 3
        assert set(keys) <= {key for key, _ in storage.objects()}
        with pytest.raises(ValueError):
            storage.download(keys[0], io.BytesIO(), 1)
    finally:
        for key in keys:
            storage.delete(key)
    with pytest.raises(ClientError):
        storage.get(keys[0])


def test_storage_requires_credentials(integration_settings: Settings) -> None:
    for config, access, secret in [
        (Config(signature_version=UNSIGNED), "", ""),
        (Config(), "wrong", "wrong"),
    ]:
        client = boto3.client(
            "s3",
            endpoint_url=integration_settings.s3_endpoint,
            aws_access_key_id=access,
            aws_secret_access_key=secret,
            region_name="us-east-1",
            config=config,
        )
        with pytest.raises(ClientError) as caught:
            client.list_objects_v2(Bucket=integration_settings.s3_bucket)
        assert caught.value.response["ResponseMetadata"]["HTTPStatusCode"] in {401, 403}


def test_schema_mismatch_fails(database: Database) -> None:
    from cardreport_server.db import SCHEMA_REVISION

    try:
        with database.pool.connection() as conn:
            conn.execute("UPDATE alembic_version SET version_num='unknown'")
        with pytest.raises(RuntimeError, match="schema mismatch"):
            database.check()
    finally:
        with database.pool.connection() as conn:
            conn.execute(
                "UPDATE alembic_version SET version_num=%s", (SCHEMA_REVISION,)
            )


def test_health(integration_settings: Settings) -> None:
    from fastapi.testclient import TestClient

    from cardreport_server.api import create_app

    with TestClient(create_app(integration_settings)) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 200


def test_renderer_migration_preserves_existing_jobs(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    from importlib import import_module

    from psycopg.errors import CheckViolation

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2]))
    migration = import_module("migrations.versions.0005_renderer")
    with database.pool.connection() as conn, conn.transaction():
        # A temporary table shadows the real queue only on this connection.
        conn.execute("CREATE TEMP TABLE reports(id integer) ON COMMIT DROP")
        conn.execute("INSERT INTO reports VALUES (1)")

        def execute(statement: str) -> None:
            conn.execute(statement)

        monkeypatch.setattr(migration.op, "execute", execute)
        migration.upgrade()
        row = conn.execute("SELECT renderer FROM reports WHERE id=1").fetchone()
        assert row is not None and row["renderer"] == "chromium"
        conn.execute("INSERT INTO reports(id,renderer) VALUES(2,'weasyprint')")
        with pytest.raises(CheckViolation), conn.transaction():
            conn.execute("INSERT INTO reports(id,renderer) VALUES(3,'unknown')")
