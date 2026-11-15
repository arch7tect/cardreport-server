"""Operator resource policy saved with each admitted report."""

from cardreport import DataLimits, ReportLimits
from pydantic import BaseModel, ConfigDict, Field


class ResourceLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    data: DataLimits = Field(default_factory=DataLimits)
    report: ReportLimits = Field(default_factory=ReportLimits)
    template_bytes: int = Field(default=1024 * 1024, ge=1)
    snapshot_bytes: int = Field(default=16 * 1024 * 1024, ge=1)
    output_bytes: int = Field(default=32 * 1024 * 1024, ge=1)


def restored_limits(value: object) -> ResourceLimits:
    # Legacy admission caps were fixed except output, which could reach 128 MiB.
    return (
        ResourceLimits(output_bytes=128 * 1024 * 1024)
        if value is None
        else ResourceLimits.model_validate(value)
    )
