import os
from collections.abc import Iterator

import pytest
from psycopg.conninfo import conninfo_to_dict
from pydantic import SecretStr

from cardreport_server.db import Database
from cardreport_server.settings import Settings
from cardreport_server.storage import Storage


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url=SecretStr("postgresql://u:p@localhost/unit_test"),
        s3_endpoint="http://localhost:8333",
        s3_access_key=SecretStr("test"),
        s3_secret_key=SecretStr("test"),
        s3_bucket="unit-test",
        s3_prefix="test/",
    )


@pytest.fixture(scope="session")
def integration_settings() -> Settings:
    if os.environ.get("CARDREPORT_TEST_RUN") != "1":
        pytest.fail(
            "Integration tests require the isolated test harness: scripts/test_integration.py"
        )
    config = Settings(_env_file=None)
    dbname = conninfo_to_dict(config.database_url.get_secret_value())["dbname"]
    if not (
        isinstance(dbname, str)
        and dbname.endswith("_test")
        and config.s3_bucket.endswith("-test")
        and config.s3_prefix.startswith("test/")
        and os.environ.get("COMPOSE_PROJECT_NAME", "").startswith("cardreport-test-")
    ):
        pytest.fail(
            "Refusing integration tests without isolated test database/bucket/project"
        )
    return config


@pytest.fixture
def database(integration_settings: Settings) -> Iterator[Database]:
    db = Database(integration_settings)
    db.open()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def storage(integration_settings: Settings) -> Storage:
    store = Storage(integration_settings)
    store.check()
    return store


@pytest.fixture
def template_spec() -> dict[str, object]:
    return {
        "format": "cardreport.template/1",
        "datasets": {
            "summary": {"cardinality": "one", "fields": {"total": {"type": "integer"}}}
        },
        "report": {
            "title": "Test report",
            "blocks": [
                {
                    "type": "card",
                    "content": {
                        "type": "kpi",
                        "label": "Total",
                        "value": {"bind": {"dataset": "summary", "field": "total"}},
                    },
                }
            ],
        },
    }
