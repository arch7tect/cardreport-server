"""Decode persisted input in the render child using CardReport's public adapters."""

import tempfile
from pathlib import Path

from cardreport import (
    DataError,
    DataLimits,
    Dataset,
    ReportTemplate,
    datasets_from_json,
    datasets_from_yaml,
)
from cardreport.adapters.csv import from_csv

from .input_files import FileResult, extract_parts

SNAPSHOT_LIMIT = DataLimits().max_json_bytes


def load_datasets(
    path: Path,
    content_type: str,
    template: ReportTemplate,
    limits: DataLimits,
    *,
    results: list[FileResult] | None = None,
) -> dict[str, Dataset]:
    if path.stat().st_size > limits.max_json_bytes:
        raise DataError("Input exceeds its size limit")
    parts = extract_parts(path, content_type)
    results = results if results is not None else []
    results.extend(FileResult(id=file.id) for file in parts.files)
    options: dict[str, str] = {}
    nulls: list[str] = []
    for key, value in parts.fields:
        if key == "csv_null":
            nulls.append(value)
        elif key in {"csv_encoding", "csv_delimiter"} and key not in options:
            options[key] = value
        else:
            raise DataError("Unknown or repeated multipart option")
    if len(nulls) > 32:
        raise DataError("At most 32 null tokens are supported")
    if not parts.files:
        raise DataError("At least one input file is required")
    delimiter = options.get("csv_delimiter", ",")
    if len(delimiter) != 1 or delimiter in "\r\n\0":
        raise DataError("CSV delimiter must be one character other than newline or NUL")
    datasets: dict[str, Dataset] = {}
    with tempfile.TemporaryDirectory(prefix="datasets-", dir=path.parent) as scratch:
        for file, result in zip(parts.files, results, strict=True):
            try:
                if file.part != "files":
                    raise DataError("Unknown multipart file part")
                if "/" in file.name or "\\" in file.name:
                    raise DataError("Input files require a plain filename")
                source = Path(file.name)
                suffix = source.suffix.lower()
                if suffix == ".csv":
                    name = source.stem
                    if name not in template.datasets:
                        raise DataError("CSV dataset is not declared in the template")
                    csv_path = Path(scratch) / str(file.id)
                    csv_path.write_bytes(file.content)
                    incoming = {
                        name: from_csv(
                            csv_path,
                            schema=template.datasets[name],
                            encoding=options.get("csv_encoding", "utf-8"),
                            delimiter=delimiter,
                            null_values=nulls,
                            limits=limits,
                        )
                    }
                elif suffix == ".json":
                    incoming = datasets_from_json(file.content, limits=limits)
                elif suffix in {".yaml", ".yml"}:
                    incoming = datasets_from_yaml(file.content, limits=limits)
                else:
                    raise DataError("Use CSV, JSON or YAML files")
                if datasets.keys() & incoming.keys():
                    result.error = "duplicate_dataset"
                    raise DataError("Duplicate dataset name")
                datasets.update(incoming)
                result.datasets = list(incoming)
                result.status = "parsed"
            except Exception:
                result.status = "failed"
                result.error = result.error or "invalid_file"
                raise
    return datasets
