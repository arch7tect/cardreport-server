"""Immutable template revisions."""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE templates (
        id varchar(64) PRIMARY KEY,
        archived boolean NOT NULL DEFAULT false,
        latest_version integer NOT NULL DEFAULT 0,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp()
    );
    CREATE TABLE template_versions (
        template_id varchar(64) NOT NULL REFERENCES templates(id),
        version integer NOT NULL CHECK (version>0),
        definition jsonb NOT NULL,
        digest varchar(64) NOT NULL,
        validated_with text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        PRIMARY KEY(template_id,version)
    );
    """)


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported")
