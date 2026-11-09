import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from cardreport import BindingError, DataError, DataLimits, ReportTemplate
from starlette.requests import Request

from cardreport_server.datasets import load_datasets
from cardreport_server.errors import APIError
from cardreport_server.intake import media_type


def multipart(tmp_path: Path, parts: list[Any]) -> tuple[Path, str]:
    request = httpx.Request("POST", "http://test", files=parts)
    path = tmp_path / "input"
    path.write_bytes(request.read())
    return path, request.headers["content-type"]


def load(tmp_path: Path, parts: list[Any], spec: dict[str, object]) -> None:
    path, kind = multipart(tmp_path, parts)
    template = ReportTemplate.from_dict(spec)
    template.bind(load_datasets(path, kind, template, DataLimits()))


def test_csv_typed_options(tmp_path: Path, template_spec: dict[str, object]) -> None:
    template = ReportTemplate.from_dict(template_spec)
    path, kind = multipart(tmp_path, [("files", ("summary.csv", b"total\n42\n"))])
    data = load_datasets(path, kind, template, DataLimits())
    assert data["summary"].rows == ((42,),)
    template.bind(data)
    assert list(tmp_path.iterdir()) == [path]


def test_csv_encoding_delimiter_and_null(tmp_path: Path) -> None:
    spec = {
        "format": "cardreport.template/1",
        "datasets": {
            "summary": {
                "cardinality": "many",
                "fields": {
                    "name": {"type": "text"},
                    "n": {"type": "integer", "nullable": True},
                },
            }
        },
        "report": {"title": "CSV", "blocks": []},
    }
    template = ReportTemplate.from_dict(spec)
    parts = [
        ("files", ("summary.csv", "name;n\nEspañol;NULL\n".encode("cp1252"))),
        ("csv_encoding", (None, "cp1252")),
        ("csv_delimiter", (None, ";")),
        ("csv_null", (None, "NULL")),
        ("csv_null", (None, "")),
    ]
    path, kind = multipart(tmp_path, parts)
    data = load_datasets(path, kind, template, DataLimits())
    assert data["summary"].rows == (("Español", None),)


@pytest.mark.parametrize("suffix", ["json", "yaml", "yml"])
def test_csv_and_bundle(
    tmp_path: Path, template_spec: dict[str, object], suffix: str
) -> None:
    parts = [
        ("files", ("summary.csv", b"total\n42\n")),
        (
            "files",
            (
                "other." + suffix,
                json.dumps(
                    {
                        "format": "cardreport.data/1",
                        "datasets": {
                            "extra": {
                                "columns": ["name"],
                                "rows": [{"name": "example"}],
                            }
                        },
                    }
                ),
            ),
        ),
    ]
    load(tmp_path, parts, template_spec)


@pytest.mark.parametrize(
    "extra",
    [
        ("files", ("summary.csv", b"total\n43\n")),
        ("files", ("unknown.csv", b"total\n43\n")),
        ("files", ("../summary.csv", b"total\n43\n")),
        ("files", ("nested\\summary.csv", b"total\n43\n")),
        ("files", ("summary.txt", b"total\n43\n")),
        ("files", (None, "total\n43\n")),
        ("unexpected", (None, "x")),
        ("csv_delimiter", (None, "xx")),
        ("csv_encoding", (None, "not-a-codec")),
        ("csv_null", (None, "x" * 1025)),
        ("data", ("data.txt", "{}")),
        (
            "files",
            (
                "data.json",
                '{"format":"cardreport.data/1","datasets":{"summary":{"columns":["total"],"rows":[{"total":1}]}}}',
            ),
        ),
    ],
)
def test_csv_bad_parts(
    tmp_path: Path, template_spec: dict[str, object], extra: Any
) -> None:
    with pytest.raises(DataError):
        load(
            tmp_path, [("files", ("summary.csv", b"total\n42\n")), extra], template_spec
        )


@pytest.mark.parametrize(
    "parts",
    [
        [("csv_encoding", (None, "utf-8"))],
        [("files", ("summary.csv", b"total\ninvalid\n"))],
        [("files", ("summary.csv", b"total\n\xff\n"))],
        [("files", ("summary.csv", b"total\n42\n"))] + [("csv_null", (None, "x"))] * 33,
        [("files", ("summary.csv", b"total\n42\n"))] * 34,
        [
            ("files", ("summary.csv", b"total\n42\n")),
            ("csv_encoding", (None, "utf-8")),
            ("csv_encoding", (None, "utf-8")),
        ],
    ],
)
def test_csv_invalid_input(
    tmp_path: Path, template_spec: dict[str, object], parts: list[Any]
) -> None:
    with pytest.raises(DataError):
        load(tmp_path, parts, template_spec)


def test_truncated_and_malformed_multipart(
    tmp_path: Path, template_spec: dict[str, object]
) -> None:
    path, kind = multipart(tmp_path, [("files", ("summary.csv", b"total\n42\n"))])
    raw = path.read_bytes()
    for bad in (raw[:-8], raw[:80], b"invalid multipart"):
        path.write_bytes(bad)
        with pytest.raises(DataError):
            load_datasets(
                path, kind, ReportTemplate.from_dict(template_spec), DataLimits()
            )


def test_aggregate_csv_limits(tmp_path: Path, template_spec: dict[str, object]) -> None:
    template = ReportTemplate.from_dict(template_spec)
    path, kind = multipart(
        tmp_path,
        [
            ("files", ("summary.csv", b"total\n42\n")),
            (
                "files",
                (
                    "extra.json",
                    '{"format":"cardreport.data/1","datasets":{"extra":{"columns":["v"],"rows":[{"v":1}]}}}',
                ),
            ),
        ],
    )
    limits = DataLimits(max_cells=1)
    datasets = load_datasets(path, kind, template, limits)
    with pytest.raises(BindingError):
        template.bind(datasets, limits=limits)
    with pytest.raises(DataError):
        load_datasets(path, kind, template, DataLimits(max_json_bytes=1))


@pytest.mark.parametrize(
    "header,valid",
    [
        ('multipart/form-data; boundary="abc x"', True),
        ("multipart/form-data", False),
        ('multipart/form-data; boundary="bad "', False),
        ('multipart/form-data; boundary="bad@"', False),
        ("multipart/form-data; boundary=" + "x" * 71, False),
        ("multipart/form-data; boundary=x; boundary=y", False),
        ("multipart/form-data; boundary=x; charset=latin1", False),
    ],
)
def test_multipart_headers(header: str, valid: bool) -> None:
    request = Request({"type": "http", "headers": [(b"content-type", header.encode())]})
    if valid:
        assert (
            media_type(request, 100, multipart=True)
            == 'multipart/form-data; boundary="abc x"'
        )
    else:
        with pytest.raises(APIError):
            media_type(request, 100, multipart=True)
    with pytest.raises(APIError):
        media_type(request, 100)


def test_csv_bom(tmp_path: Path, template_spec: dict[str, object]) -> None:
    load(
        tmp_path,
        [
            ("files", ("summary.csv", b"\xef\xbb\xbftotal\n42\n")),
            ("csv_encoding", (None, "utf-8-sig")),
        ],
        template_spec,
    )


def test_csv_maximum_option_fields(
    tmp_path: Path, template_spec: dict[str, object]
) -> None:
    load(
        tmp_path,
        [
            ("files", ("summary.csv", b"total\n42\n")),
            ("csv_encoding", (None, "utf-8")),
            ("csv_delimiter", (None, ",")),
            *[("csv_null", (None, f"NULL-{index}")) for index in range(32)],
        ],
        template_spec,
    )


def test_child_applies_combined_limits(
    tmp_path: Path, template_spec: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    import signal
    import sys
    import time

    from cardreport_server import render_child

    path, kind = multipart(
        tmp_path,
        [
            ("files", ("summary.csv", b"total\n42\n")),
            (
                "files",
                (
                    "extra.json",
                    '{"format":"cardreport.data/1","datasets":{"extra":{"columns":["v"],"rows":[{"v":1}]}}}',
                ),
            ),
        ],
    )
    (tmp_path / "template.json").write_text(json.dumps(template_spec))
    (tmp_path / "options.json").write_text(
        json.dumps(
            {
                "input_type": kind,
                "data_limits": {"max_cells": 1},
                "output": "html",
                "renderer": "chromium",
                "render_timeout": 30,
                "render_deadline": time.monotonic() + 30,
                "output_limit": 16 * 1024 * 1024,
            }
        )
    )
    monkeypatch.setattr(sys, "argv", ["render_child", str(path.parent)])
    monkeypatch.setattr(signal, "signal", lambda *args: None)
    render_child.main()
    outcome = json.loads((tmp_path / "outcome.json").read_text())
    assert outcome["code"] == "invalid_data" and outcome["stage"] == "bind"
    assert not (tmp_path / "result").exists()


@pytest.mark.parametrize("duplicate", [False, True])
def test_multiple_bundles_without_csv(
    tmp_path: Path, template_spec: dict[str, object], duplicate: bool
) -> None:
    parts = []
    for index, suffix in enumerate(["yaml", "json", "yml", "json"]):
        name = "summary" if index == 0 or duplicate else f"extra{index}"
        raw = json.dumps(
            {
                "format": "cardreport.data/1",
                "datasets": {name: {"columns": ["total"], "rows": [{"total": index}]}},
            }
        )
        parts.append(("files", ("data." + suffix, raw)))
    if duplicate:
        with pytest.raises(DataError, match="Duplicate dataset"):
            load(tmp_path, parts, template_spec)
    else:
        load(tmp_path, parts, template_spec)


def test_child_snapshot_uses_typed_values(
    tmp_path: Path, template_spec: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    import signal
    import sys
    import time

    from cardreport import datasets_from_json

    from cardreport_server import render_child

    path, kind = multipart(
        tmp_path, [("files", ("summary.csv", b"total\n999999999999000\n"))]
    )
    (tmp_path / "template.json").write_text(json.dumps(template_spec))
    (tmp_path / "options.json").write_text(
        json.dumps(
            {
                "input_type": kind,
                "data_limits": {},
                "output": "html",
                "renderer": "chromium",
                "render_timeout": 30,
                "render_deadline": time.monotonic() + 30,
                "output_limit": 16 * 1024 * 1024,
            }
        )
    )
    monkeypatch.setattr(sys, "argv", ["render_child", str(path.parent)])
    monkeypatch.setattr(signal, "signal", lambda *args: None)
    render_child.main()
    assert json.loads((tmp_path / "outcome.json").read_text()) == {"ok": True}
    snapshot = datasets_from_json((tmp_path / "data.json").read_bytes())
    assert snapshot["summary"].rows == ((999999999999000,),)
    # A CSV can fit the raw limit but expand beyond the canonical snapshot limit.
    monkeypatch.setattr(render_child, "SNAPSHOT_LIMIT", 1)
    render_child.main()
    assert (
        json.loads((tmp_path / "outcome.json").read_text())["code"]
        == "data_snapshot_too_large"
    )
