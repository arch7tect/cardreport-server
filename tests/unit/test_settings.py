import pytest
from pydantic import ValidationError

from cardreport_server.settings import Settings


@pytest.mark.parametrize(
    "changes",
    [
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
