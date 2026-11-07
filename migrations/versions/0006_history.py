"""Indexes for retained report history, without changing job data."""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX reports_history ON reports(created_at DESC,id DESC)")
    op.execute(
        "CREATE INDEX reports_template_history ON reports(template_id,created_at DESC,id DESC)"
    )


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported")
