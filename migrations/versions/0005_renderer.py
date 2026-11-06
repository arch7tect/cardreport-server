"""Persist the selected renderer, preserving Chromium for existing jobs."""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE reports ADD COLUMN renderer text NOT NULL DEFAULT 'chromium'
        CHECK(renderer IN ('chromium','weasyprint'));
    """)


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported")
