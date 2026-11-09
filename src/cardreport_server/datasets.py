"""Decode persisted input in the render child using CardReport's public adapters."""

import asyncio
import shutil
import tempfile
from collections.abc import AsyncGenerator
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
from starlette.datastructures import Headers, UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

SNAPSHOT_LIMIT = DataLimits().max_json_bytes


class CompleteMultipartParser(MultiPartParser):
    complete = False

    def on_end(self) -> None:
        self.complete = True


def load_datasets(
    path: Path, content_type: str, template: ReportTemplate, limits: DataLimits
) -> dict[str, Dataset]:
    if path.stat().st_size > limits.max_json_bytes:
        raise DataError("Input exceeds its size limit")
    if content_type.startswith("multipart/form-data;"):
        return asyncio.run(_multipart(path, content_type, template, limits))
    return _bundle(path.read_bytes(), content_type, limits)


def _bundle(raw: bytes, kind: str, limits: DataLimits) -> dict[str, Dataset]:
    if kind == "application/json":
        return datasets_from_json(raw, limits=limits)
    if kind == "application/yaml":
        return datasets_from_yaml(raw, limits=limits)
    raise DataError("Unsupported dataset bundle type")


async def _multipart(
    path: Path, content_type: str, template: ReportTemplate, limits: DataLimits
) -> dict[str, Dataset]:
    async def chunks() -> AsyncGenerator[bytes, None]:
        with path.open("rb") as stream:
            while chunk := stream.read(64 * 1024):
                yield chunk
        # python-multipart finalize() alone does not reject a truncated body.
        # Raise inside Starlette's parse loop so it also closes unfinished files.
        if not parser.complete:
            raise MultiPartException("Incomplete multipart body")

    parser = CompleteMultipartParser(
        Headers({"Content-Type": content_type}),
        chunks(),
        max_files=limits.max_datasets,
        max_fields=34,
        max_part_size=1024,
    )
    try:
        form = await parser.parse()
    except MultiPartException:
        raise DataError("Invalid multipart input") from None
    try:
        options: dict[str, str] = {}
        nulls: list[str] = []
        uploads: list[UploadFile] = []
        for key, value in form.multi_items():
            if isinstance(value, str):
                if key == "csv_null":
                    nulls.append(value)
                elif key in {"csv_encoding", "csv_delimiter"} and key not in options:
                    options[key] = value
                else:
                    raise DataError("Unknown or repeated multipart option")
            elif key == "files":
                filename = value.filename or ""
                if "/" in filename or "\\" in filename:
                    raise DataError("Input files require a plain filename")
                if Path(filename).suffix.lower() not in {
                    ".csv",
                    ".json",
                    ".yaml",
                    ".yml",
                }:
                    raise DataError("Use CSV, JSON or YAML files")
                uploads.append(value)
            else:
                raise DataError("Unknown multipart file part")
        if len(nulls) > 32:
            raise DataError("At most 32 null tokens are supported")
        if not uploads:
            raise DataError("At least one input file is required")
        encoding = options.get("csv_encoding", "utf-8")
        delimiter = options.get("csv_delimiter", ",")
        if len(delimiter) != 1 or delimiter in "\r\n\0":
            raise DataError(
                "CSV delimiter must be one character other than newline or NUL"
            )
        datasets: dict[str, Dataset] = {}
        with tempfile.TemporaryDirectory(
            prefix="datasets-", dir=path.parent
        ) as scratch:
            for index, upload in enumerate(uploads):
                source_path = Path(upload.filename or "")
                if source_path.suffix.lower() == ".csv":
                    name = source_path.stem
                    if name not in template.datasets:
                        raise DataError("CSV dataset is not declared in the template")
                    csv_path = Path(scratch) / str(index)
                    with csv_path.open("wb") as target:
                        shutil.copyfileobj(upload.file, target, length=64 * 1024)
                    incoming = {
                        name: from_csv(
                            csv_path,
                            schema=template.datasets[name],
                            encoding=encoding,
                            delimiter=delimiter,
                            null_values=nulls,
                            limits=limits,
                        )
                    }
                else:
                    kind = (
                        "application/json"
                        if source_path.suffix.lower() == ".json"
                        else "application/yaml"
                    )
                    incoming = _bundle(await upload.read(), kind, limits)
                if datasets.keys() & incoming.keys():
                    raise DataError("Duplicate dataset name")
                datasets.update(incoming)
        # bind(..., limits=limits) checks cumulative cells/text across all inputs.
        return datasets
    finally:
        await form.close()
