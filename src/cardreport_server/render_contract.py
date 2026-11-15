"""Owned JSON messages exchanged by the supervisor and render process."""

from typing import Literal, TypedDict

Output = Literal["pdf", "html"]
RendererName = Literal["chromium", "weasyprint"]


class RenderOptions(TypedDict):
    input_type: str
    output: Output
    renderer: RendererName
    render_timeout: float
    render_deadline: float
    limits: dict[str, object]


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
