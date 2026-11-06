"""Run only from the explicit Alembic command."""

import psycopg
from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from cardreport_server.settings import Settings

settings = Settings()

engine = create_engine(
    "postgresql+psycopg://",
    poolclass=NullPool,
    creator=lambda: psycopg.connect(settings.database_url.get_secret_value()),
)
with engine.connect() as connection:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
