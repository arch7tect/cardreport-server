"""Preserve input parse results and configure template retention."""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE templates ADD COLUMN retention_seconds integer
        CHECK (retention_seconds BETWEEN 1 AND 2147483000);
    ALTER TABLE reports ADD COLUMN input_files jsonb;
    """)


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported")
