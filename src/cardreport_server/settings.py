"""Validated operator configuration; secrets never enter public responses."""

from pathlib import Path
from typing import Self
from urllib.parse import urlsplit

from psycopg.conninfo import conninfo_to_dict
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CARDREPORT_", extra="ignore", allow_inf_nan=False
    )

    database_url: SecretStr
    s3_endpoint: str
    s3_access_key: SecretStr
    s3_secret_key: SecretStr
    s3_bucket: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
    s3_region: str = "us-east-1"
    s3_prefix: str = Field(default="cardreport/", pattern=r"^[a-zA-Z0-9_/-]+/$")
    db_pool_size: int = Field(default=8, ge=1, le=64)
    io_timeout: float = Field(default=5, gt=0, le=30)
    db_connect_timeout: int = Field(default=5, ge=2, le=120)
    db_statement_timeout: float = Field(default=5, gt=0, le=120)
    db_lock_timeout: float = Field(default=3, gt=0, le=120)
    input_limit: int = Field(default=16 * 1024 * 1024, ge=1, le=16 * 1024 * 1024)
    data_max_rows: int = Field(default=2000, ge=1, le=2000)
    data_max_cells: int = Field(default=100000, ge=1, le=100000)
    output_limit: int = Field(default=32 * 1024 * 1024, ge=1024, le=128 * 1024 * 1024)
    upload_slots: int = Field(default=4, ge=1, le=64)
    upload_timeout: float = Field(default=120, gt=0, le=600)
    upload_idle_timeout: float = Field(default=30, gt=0, le=120)
    backlog_limit: int = Field(default=1000, ge=1, le=100000)
    admission_enabled: bool = True
    worker_concurrency: int = Field(default=2, ge=1, le=32)
    lease_seconds: float = Field(default=60, ge=3, le=600)
    heartbeat_seconds: float = Field(default=15, ge=0.2, le=120)
    attempt_timeout: float = Field(default=120, ge=5, le=600)
    render_timeout: float = Field(default=300, gt=0)
    startup_render_timeout: float = Field(default=30, gt=0)
    startup_timeout: float = Field(default=75, gt=0)
    health_max_age: float = Field(default=60, gt=0)
    cleanup_grace: float = Field(default=5, ge=5, le=30)
    shutdown_grace: float = Field(default=130, ge=1, le=900)
    max_attempts: int = Field(default=3, ge=1, le=10)
    poll_seconds: float = Field(default=1, ge=0.05, le=30)
    queue_max_age: int = Field(default=3600, ge=1)
    retry_delay: float = Field(default=5, ge=0, le=120)
    retry_max_delay: float = Field(default=120, ge=0)
    input_retention: int = Field(default=3600, ge=1)
    result_retention: int = Field(default=86400, ge=1)
    metadata_retention: int = Field(default=604800, ge=1)
    download_timeout: float = Field(default=120, gt=0, le=600)
    orphan_grace: int = Field(default=900, ge=1)
    maintenance_interval: float = Field(default=30, ge=0.2, le=300)
    maintenance_batch_size: int = Field(default=100, ge=1, le=1000)
    temp_root: Path = Path("/tmp/cardreport-worker")
    image_id: str = "development"

    @property
    def io_reserve(self) -> float:
        # Headroom for S3 connect/read waits across its two SDK attempts.
        # This is not a total I/O deadline; the supervisor enforces attempt expiry.
        return 4 * self.io_timeout

    @model_validator(mode="after")
    def relationships(self) -> Self:
        try:
            info = conninfo_to_dict(self.database_url.get_secret_value())
            if not info.get("dbname"):
                raise ValueError
        except Exception:
            raise ValueError(
                "database_url must be a PostgreSQL DSN with a database"
            ) from None
        endpoint = urlsplit(self.s3_endpoint)
        if (
            endpoint.scheme not in {"http", "https"}
            or not endpoint.hostname
            or endpoint.username
        ):
            raise ValueError(
                "s3_endpoint must be an HTTP(S) endpoint without credentials"
            )
        if self.db_lock_timeout > self.db_statement_timeout:
            raise ValueError("db_lock_timeout must not exceed db_statement_timeout")
        if self.startup_timeout <= 2 * self.startup_render_timeout:
            raise ValueError("startup_timeout must exceed two renderer smoke budgets")
        if self.health_max_age <= self.poll_seconds:
            raise ValueError("health_max_age must exceed poll_seconds")
        if self.retry_delay > self.retry_max_delay:
            raise ValueError("retry_delay must not exceed retry_max_delay")
        if self.upload_idle_timeout > self.upload_timeout:
            raise ValueError("upload_idle_timeout must not exceed upload_timeout")
        if self.heartbeat_seconds * 3 >= self.lease_seconds:
            raise ValueError("lease_seconds must exceed three heartbeat intervals")
        if self.attempt_timeout <= self.cleanup_grace + self.io_reserve + 1:
            raise ValueError(
                "attempt_timeout must include I/O, cleanup and render budgets"
            )
        if self.cleanup_grace >= self.attempt_timeout:
            raise ValueError("cleanup_grace must be less than attempt_timeout")
        if (
            self.orphan_grace
            <= max(self.upload_timeout, self.attempt_timeout) + self.io_reserve
        ):
            raise ValueError(
                "orphan_grace must exceed upload/attempt duration plus I/O margin"
            )
        if (
            self.metadata_retention
            <= max(self.input_retention, self.result_retention) + self.download_timeout
        ):
            raise ValueError("metadata retention must outlast artifacts and downloads")
        if not self.temp_root.is_absolute() or len(self.temp_root.parts) < 3:
            raise ValueError("temp_root must be a dedicated absolute subdirectory")
        return self
