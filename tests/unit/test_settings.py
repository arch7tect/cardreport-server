import pytest
from pydantic import ValidationError

from cardreport_server.settings import Settings


@pytest.mark.parametrize(
    "changes",
    [
        {"render_timeout": 0},
        {"render_timeout": float("inf")},
        {"render_timeout": float("nan")},
        {"startup_timeout": 60},
        {"health_max_age": 1},
        {"retry_max_delay": 4},
        {"db_lock_timeout": 6},
        {"maintenance_batch_size": 1001},
        {"input_limit": 17 * 1024 * 1024},
        {"worker_concurrency": 0},
        {"lease_seconds": 45},
        {"upload_timeout": 10},
        {"orphan_grace": 60},
        {"temp_root": "/"},
        {"s3_endpoint": "file:///tmp"},
        {"metadata_retention": 10},
    ],
)
def test_invalid_limits(settings: Settings, changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(settings.model_dump() | changes)


def test_secrets_not_in_repr(settings: Settings) -> None:
    assert "postgresql://u:p" not in repr(settings)
    assert settings.worker_concurrency == 2
