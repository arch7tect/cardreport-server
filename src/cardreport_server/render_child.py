"""One credential-free attempt; the supervisor owns every external resource."""

import json
import os
import signal
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import NoReturn
from uuid import uuid4

from cardreport import (
    BindingError,
    ChromiumRenderer,
    DataError,
    DataLimits,
    DependencyError,
    LayoutOverflowError,
    Renderer,
    RenderTimeoutError,
    ReportTemplate,
    TemplateError,
    UnsupportedFeatureError,
    ValidationError,
    WeasyPrintRenderer,
    datasets_to_json,
)

from .datasets import SNAPSHOT_LIMIT, load_datasets


class Cancelled(BaseException):
    pass


def cancel(signum: int, frame: object) -> NoReturn:
    # Unwind CardReport's finally block, which stops its detached renderer tree.
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    raise Cancelled


def main() -> None:
    signal.signal(signal.SIGTERM, cancel)
    directory = Path(sys.argv[1])
    outcome: dict[str, object]
    stage = "bind"
    try:
        options = json.loads((directory / "options.json").read_text())
        template = ReportTemplate.from_json((directory / "template.json").read_bytes())
        limits = DataLimits(**options["data_limits"])
        datasets = load_datasets(
            directory / "input", options["input_type"], template, limits
        )
        report = template.bind(datasets, limits=limits)
        stage = "snapshot"
        snapshot = datasets_to_json(
            datasets, limits=replace(limits, max_json_bytes=SNAPSHOT_LIMIT)
        )
        (directory / "data.json").write_text(snapshot, encoding="utf-8")
        stage = "render"
        remaining = min(
            options["render_deadline"] - time.monotonic(), options["render_timeout"]
        )
        if remaining <= 0:
            raise RenderTimeoutError("Execution deadline expired")
        renderer_types: dict[str, type[Renderer]] = {
            "chromium": ChromiumRenderer,
            "weasyprint": WeasyPrintRenderer,
        }
        renderer = renderer_types[options["renderer"]]()
        payload = (
            report.to_pdf(timeout=remaining, renderer=renderer)
            if options["output"] == "pdf"
            else report.to_html(renderer=renderer).encode()
        )
        if len(payload) > options["output_limit"]:
            outcome = {
                "code": "output_too_large",
                "stage": "render",
                "message": "Report exceeds the output size limit",
            }
        else:
            (directory / "result").write_bytes(payload)
            outcome = {"ok": True}
    except Cancelled:
        outcome = {
            "code": "cancelled",
            "stage": "render",
            "message": "Report execution stopped",
        }
    except (DataError, BindingError, TemplateError, ValidationError):
        if stage == "snapshot":
            outcome = {
                "code": "data_snapshot_too_large",
                "stage": "bind",
                "message": "Normalized report data exceeds the 16 MiB snapshot limit",
            }
        else:
            outcome = {
                "code": "invalid_data" if stage == "bind" else "render_failed",
                "stage": stage,
                "message": (
                    "Datasets do not satisfy the template or data limits"
                    if stage == "bind"
                    else "Report export validation failed"
                ),
            }
    except LayoutOverflowError:
        outcome = {
            "code": "layout_overflow",
            "stage": "render",
            "message": "Report content does not fit; adjust the template layout",
        }
    except UnsupportedFeatureError:
        outcome = {
            "code": "unsupported_feature",
            "stage": "render",
            "message": "Renderer does not support this template feature",
        }
    except DependencyError:
        outcome = {
            "code": "renderer_unavailable",
            "stage": "render",
            "message": "Renderer dependency unavailable",
        }
    except RenderTimeoutError:
        outcome = {
            "code": "render_timeout",
            "stage": "render",
            "message": "Report rendering exceeded its time budget",
        }
    except Exception as error:
        outcome = {
            "code": "render_failed",
            "stage": "render",
            "message": "Report rendering failed",
            "id": uuid4().hex,
            "internal_type": type(error).__name__,
        }
    (directory / "outcome.tmp").write_text(json.dumps(outcome))
    os.replace(directory / "outcome.tmp", directory / "outcome.json")


def child_environment(directory: Path) -> dict[str, str]:
    allowed = (
        "PATH",
        "LANG",
        "LC_ALL",
        "PLAYWRIGHT_BROWSERS_PATH",
        "FONTCONFIG_PATH",
        "SSL_CERT_FILE",
    )
    return {key: os.environ[key] for key in allowed if key in os.environ} | {
        "HOME": str(directory),
        "TMPDIR": str(directory),
        "PYTHONUNBUFFERED": "1",
    }


if __name__ == "__main__":
    main()
