"""Preserve operator resource budgets for accepted reports."""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE reports ADD COLUMN resource_limits jsonb")


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported")
