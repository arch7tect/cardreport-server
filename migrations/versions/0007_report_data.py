"""Retain the winning report's typed dataset snapshot alongside its result."""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE reports ADD COLUMN data_key text UNIQUE,
        ADD COLUMN data_size bigint,
        ADD COLUMN data_hash text,
        ADD CONSTRAINT report_data_result CHECK(data_key IS NULL OR result_key IS NOT NULL);
    """)


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported")
