import base64
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import make_conninfo

from cardreport_server.api import create_app
from cardreport_server.db import SCHEMA_REVISION, Database
from cardreport_server.settings import Settings
from cardreport_server.templates import register

pytestmark = pytest.mark.integration


def seed(
    database: Database, slug: str, ids: list[UUID], created: list[datetime]
) -> None:
    with database.pool.connection() as conn:
        for identifier, stamp in zip(ids, created, strict=True):
            conn.execute(
                """INSERT INTO reports(id,template_id,template_version,state,input_key,
                input_type,input_size,input_hash,output_kind,input_retention,
                result_retention,metadata_retention,created_at)
                VALUES(%s,%s,1,'failed',%s,'application/json',2,'test','pdf',60,60,120,%s)""",
                (identifier, slug, str(identifier), stamp),
            )


def test_history_pagination_and_filters(
    database: Database, integration_settings: Settings, template_spec: dict[str, object]
) -> None:
    slug = "history-" + uuid4().hex
    register(database, slug, json.dumps(template_spec).encode(), "application/json")
    now = datetime.now(UTC)
    ids = sorted([uuid4() for _ in range(5)])
    stamps = [
        now,
        now,
        now,
        now + timedelta(microseconds=1),
        now - timedelta(microseconds=1),
    ]
    seed(database, slug, ids, stamps)
    expected = [str(ids[i]) for i in (3, 2, 1, 0, 4)]
    with TestClient(create_app(integration_settings)) as client:
        params: dict[str, str | int] = {"template_id": slug, "limit": 2}
        seen = []
        while True:
            response = client.get("/v1/reports", params=params)
            assert response.status_code == 200, response.text
            page = response.json()
            for item in page["items"]:
                assert item == client.get(f"/v1/reports/{item['id']}").json()
                assert (
                    not {
                        "input_key",
                        "input_hash",
                        "result_key",
                        "attempt_token",
                        "lease_until",
                    }
                    & item.keys()
                )
                seen.append(item["id"])
            if page["next"] is None:
                break
            params["after"] = page["next"]
        assert seen == expected
        first = client.get(
            "/v1/reports", params={"template_id": slug, "limit": 2}
        ).json()
        with database.pool.connection() as conn:
            conn.execute("DELETE FROM reports WHERE id=%s", (first["items"][-1]["id"],))
            conn.execute("UPDATE templates SET archived=true WHERE id=%s", (slug,))
            conn.execute(
                "UPDATE reports SET state='expired',terminal_state='failed' WHERE id=%s",
                (ids[0],),
            )
        newest = uuid4()
        seed(database, slug, [newest], [now + timedelta(seconds=1)])
        rest = client.get(
            "/v1/reports", params={"template_id": slug, "after": first["next"]}
        ).json()
        assert [row["id"] for row in rest["items"]] == expected[2:]
        expired = client.get(
            "/v1/reports", params={"template_id": slug, "state": "expired"}
        ).json()
        assert (
            len(expired["items"]) == 1
            and expired["items"][0]["terminal_state"] == "failed"
        )
        assert client.get(
            "/v1/reports", params={"template_id": "missing-" + uuid4().hex}
        ).json() == {"items": [], "next": None}
        refreshed = client.get("/v1/reports", params={"template_id": slug}).json()
        assert refreshed["items"][0]["id"] == str(newest)
        assert len(client.get("/v1/reports").json()["items"]) <= 50
        for invalid in (
            {"state": "lost"},
            {"template_id": "UPPER"},
            {"limit": 0},
            {"limit": 101},
            {"after": "x" * 513},
        ):
            assert client.get("/v1/reports", params=invalid).status_code == 422
        for value in (
            "",
            "%%%",
            "!!!!",
            "e30",
            "[1]",
            [2, now.isoformat(), str(ids[0])],
            [True, now.isoformat(), str(ids[0])],
            [1, "2026-01-01", str(ids[0])],
            [1, now.isoformat(), "bad-uuid"],
            [1, "9999-12-31T23:59:59-23:59", str(ids[0])],
        ):
            cursor = (
                value
                if isinstance(value, str)
                else base64.urlsafe_b64encode(json.dumps(value).encode()).decode()
            )
            response = client.get("/v1/reports", params={"after": cursor})
            assert response.status_code == 422, response.text
            assert response.json()["error"]["code"] == "invalid_cursor"


def test_history_migration_and_query_plan(integration_settings: Settings) -> None:
    schema = "history_test_" + uuid4().hex
    dsn = integration_settings.database_url.get_secret_value()
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(f'CREATE SCHEMA "{schema}"')
        try:
            scoped = make_conninfo(dsn, options=f"-csearch_path={schema}")
            env = os.environ.copy() | {"CARDREPORT_DATABASE_URL": scoped}
            root = Path(__file__).resolve().parents[2]

            def migrate(target: str) -> None:
                subprocess.run(
                    [sys.executable, "-m", "alembic", "upgrade", target],
                    env=env,
                    cwd=root,
                    check=True,
                    capture_output=True,
                )

            migrate("0005")
            with psycopg.connect(scoped, autocommit=True) as conn:
                conn.execute(
                    "INSERT INTO templates(id,latest_version) VALUES('history',1),('background',1)"
                )
                conn.execute(
                    "INSERT INTO template_versions(template_id,version,definition,digest,validated_with) VALUES('history',1,'{}','test','test'),('background',1,'{}','test','test')"
                )
                conn.execute("""INSERT INTO reports(id,template_id,template_version,state,input_key,input_type,input_size,input_hash,output_kind,input_retention,result_retention,metadata_retention)
                    SELECT md5(i::text)::uuid,CASE WHEN i%100=0 THEN 'history' ELSE 'background' END,1,CASE WHEN i=1 THEN 'queued' ELSE 'failed' END,i::text,'application/json',2,'test','pdf',60,60,120 FROM generate_series(1,10000) i""")
                before = conn.execute(
                    "SELECT id,state,input_key FROM reports ORDER BY id"
                ).fetchall()
                migrate("head")
                migrate("head")
                assert (
                    conn.execute(
                        "SELECT id,state,input_key FROM reports ORDER BY id"
                    ).fetchall()
                    == before
                )
                assert conn.execute(
                    "SELECT version_num FROM alembic_version"
                ).fetchone() == (SCHEMA_REVISION,)
                conn.execute("ANALYZE reports")
                for clause, index in [
                    ("", "reports_history"),
                    ("WHERE template_id='history'", "reports_template_history"),
                ]:
                    plan = conn.execute(
                        f"EXPLAIN (FORMAT JSON) SELECT id,created_at FROM reports {clause} ORDER BY created_at DESC,id DESC LIMIT 51"
                    ).fetchone()
                    assert plan is not None and index in json.dumps(plan)
        finally:
            admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
