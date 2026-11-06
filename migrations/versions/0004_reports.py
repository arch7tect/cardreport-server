"""Durable reports, token-fenced attempts and retention snapshots."""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE reports (
        id uuid PRIMARY KEY, template_id varchar(64) NOT NULL, template_version integer NOT NULL,
        FOREIGN KEY(template_id,template_version) REFERENCES template_versions(template_id,version),
        state text NOT NULL DEFAULT 'queued' CHECK(state IN ('queued','running','succeeded','failed','expired')),
        input_key text NOT NULL UNIQUE, input_type text NOT NULL, input_size bigint NOT NULL,
        input_hash text NOT NULL, output_kind text NOT NULL CHECK(output_kind IN ('pdf','html')),
        result_key text UNIQUE, result_size bigint, result_hash text,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(), started_at timestamptz,
        finished_at timestamptz, next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        attempt_no integer NOT NULL DEFAULT 0, attempt_token uuid, lease_until timestamptz,
        attempt_deadline timestamptz, error jsonb, terminal_state text,
        input_retention integer NOT NULL, result_retention integer NOT NULL, metadata_retention integer NOT NULL,
        input_expires_at timestamptz, result_expires_at timestamptz, metadata_expires_at timestamptz,
        input_deleted boolean NOT NULL DEFAULT false, result_deleted boolean NOT NULL DEFAULT false,
        engine_version text, image_id text, service_version text
    );
    CREATE INDEX reports_queue ON reports(next_attempt_at,created_at,id) WHERE state='queued';
    CREATE INDEX reports_leases ON reports(lease_until) WHERE state='running';
    CREATE INDEX reports_metadata_expiry ON reports(metadata_expires_at);
    """)


def downgrade() -> None:
    raise RuntimeError("Downgrades are not supported")
