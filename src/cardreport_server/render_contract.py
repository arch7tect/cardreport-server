"""Owned JSON messages exchanged by the supervisor and render process."""

from typing import Literal, TypedDict

Output = Literal["pdf", "html"]
RendererName = Literal["chromium", "weasyprint"]


class DataLimitOptions(TypedDict, total=False):
    max_rows: int
    max_cells: int
    max_json_bytes: int


class RenderOptions(TypedDict):
    input_type: str
    output: Output
    renderer: RendererName
    render_timeout: float
    render_deadline: float
    data_limits: DataLimitOptions
    output_limit: int


class Outcome(TypedDict, total=False):
    ok: bool
    code: str
    stage: str
    message: str
    id: str
    internal_type: str
    diagnostic: dict[str, object]
    retryable: bool


class Artifact(TypedDict):
    key: str
    size: int
    hash: str
