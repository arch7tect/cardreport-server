import json
from pathlib import Path

import httpx
import pytest
from cardreport import DataError, DataLimits, ReportTemplate

from cardreport_server.datasets import load_datasets
from cardreport_server.input_files import FileResult, extract_parts, read_results


def test_files_preserve_bytes_and_failure_order(
    tmp_path: Path, template_spec: dict[str, object]
) -> None:
    parts = [
        ("files", ("summary.csv", b"total\r\nnot-a-number\r\n")),
        ("files", ("summary.csv", b"total\n42\n")),
    ]
    request = httpx.Request("POST", "http://test", files=parts)
    path = tmp_path / "input"
    path.write_bytes(request.read())
    kind = request.headers["content-type"]
    extracted = extract_parts(path, kind)
    assert [f.id for f in extracted.files] == [1, 2]
    assert [f.content for f in extracted.files] == [p[1][1] for p in parts]
    results: list[FileResult] = []
    with pytest.raises(DataError):
        load_datasets(
            path,
            kind,
            ReportTemplate.from_dict(template_spec),
            DataLimits(),
            results=results,
        )
    assert [r.status for r in results] == ["failed", "skipped"]
    assert results[0].error == "invalid_file"
    (tmp_path / "files.json").write_text(json.dumps([r.model_dump() for r in results]))
    assert read_results(tmp_path, kind) == [r.model_dump() for r in results]
    (tmp_path / "files.json").write_text('[{"id":2,"status":"parsed"}]')
    with pytest.raises(ValueError):
        read_results(tmp_path, kind)


def test_raw_file_and_unrecognized_parts(tmp_path: Path) -> None:
    path = tmp_path / "input"
    raw = b"# original YAML comments\ninvalid: ["
    path.write_bytes(raw)
    file = extract_parts(path, "application/yaml").files[0]
    assert file.name == "input.yaml" and file.content == raw
    request = httpx.Request(
        "POST", "http://test", files=[("unexpected", ("../../data.txt", raw))]
    )
    path.write_bytes(request.read())
    file = extract_parts(path, request.headers["content-type"]).files[0]
    assert file.part == "unexpected" and file.name == "../../data.txt"
    path.write_bytes(path.read_bytes()[:-8])
    with pytest.raises(DataError):
        extract_parts(path, request.headers["content-type"])


def test_metadata_expansion_is_bounded(tmp_path: Path) -> None:
    request = httpx.Request(
        "POST", "http://test", files=[("files", ("x" * 3000 + ".csv", b"v\n1"))] * 25
    )
    path = tmp_path / "input"
    path.write_bytes(request.read())
    with pytest.raises(DataError, match="metadata"):
        extract_parts(path, request.headers["content-type"])
