"""Short PostgreSQL transactions, shared by the HTTP and worker processes."""

from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .settings import Settings

SCHEMA_REVISION = "0008"


class Database:
    def __init__(self, settings: Settings) -> None:
        self.pool: ConnectionPool[Connection[dict[str, Any]]] = ConnectionPool(
            settings.database_url.get_secret_value(),
            min_size=0,
            max_size=settings.db_pool_size,
            timeout=settings.io_timeout,
            kwargs={
                "row_factory": dict_row,
                "connect_timeout": settings.db_connect_timeout,
                "options": (
                    f"-c statement_timeout={max(1, int(settings.db_statement_timeout * 1000))} "
                    f"-c lock_timeout={max(1, int(settings.db_lock_timeout * 1000))}"
                ),
            },
            open=False,
        )

    def open(self) -> None:
        self.pool.open()
        self.check()

    def check(self) -> None:
        with self.pool.connection() as conn:
            row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
            if row is None or row["version_num"] != SCHEMA_REVISION:
                raise RuntimeError(
                    "Database schema mismatch; run the explicit migration step"
                )

    def close(self) -> None:
        self.pool.close()
