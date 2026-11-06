"""Initialize the revision gate."""

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    raise RuntimeError(
        "Downgrades are not supported; use a verified rollback procedure"
    )
