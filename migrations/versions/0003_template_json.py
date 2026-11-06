"""Preserve canonical template serialization and repair unreleased JSONB digests."""

import hashlib

from alembic import op
from cardreport import ReportTemplate
from sqlalchemy import text

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    # Preserve immutable migration history; 0002 was applied only to development fixtures.
    op.execute(
        "ALTER TABLE template_versions ALTER COLUMN definition TYPE json USING definition::json"
    )
    rows = connection.execute(
        text("SELECT template_id,version,definition FROM template_versions")
    )
    for row in rows:
        canonical = ReportTemplate.from_dict(row.definition).to_json()
        connection.execute(
            text(
                "UPDATE template_versions SET definition=CAST(:definition AS json),digest=:digest "
                "WHERE template_id=:id AND version=:version"
            ),
            {
                "definition": canonical,
                "digest": hashlib.sha256(canonical.encode()).hexdigest(),
                "id": row.template_id,
                "version": row.version,
            },
        )


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported")
