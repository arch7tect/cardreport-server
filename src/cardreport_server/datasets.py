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
        max_files=limits.max_datasets + 1,
        max_fields=35,
        max_part_size=1024,
    )
    try:
        form = await parser.parse()
    except MultiPartException:
        raise DataError("Invalid multipart input") from None
    try:
        options: dict[str, str] = {}
        nulls: list[str] = []
        csvs: list[tuple[str, UploadFile]] = []
        bundle: UploadFile | None = None
        data_seen = False
        for key, value in form.multi_items():
            if key == "data":
                if data_seen:
                    raise DataError("Repeated multipart data part")
                data_seen = True
                if isinstance(value, UploadFile):
                    bundle = value
                elif value != "":
                    raise DataError("The data part must be a JSON/YAML file")
                # Swagger sends an empty text part for an unselected optional file.
                continue
            if isinstance(value, str):
                if key == "csv_null":
                    nulls.append(value)
                elif key in {"csv_encoding", "csv_delimiter"} and key not in options:
                    options[key] = value
                else:
                    raise DataError("Unknown or repeated multipart option")
            elif key == "files":
                filename = value.filename or ""
                # Caller filenames are metadata only, never filesystem paths.
                if (
                    "/" in filename
                    or "\\" in filename
                    or not filename.lower().endswith(".csv")
                ):
                    raise DataError("CSV files require a plain .csv filename")
                name = filename[:-4]
                if name not in template.datasets:
                    raise DataError("CSV dataset is not declared in the template")
                csvs.append((name, value))
            else:
                raise DataError("Unknown or repeated multipart file part")
        if len(nulls) > 32:
            raise DataError("At most 32 null tokens are supported")
        if not csvs:
            raise DataError("At least one CSV file is required")
        encoding = options.get("csv_encoding", "utf-8")
        delimiter = options.get("csv_delimiter", ",")
        if len(delimiter) != 1 or delimiter in "\r\n\0":
            raise DataError(
                "CSV delimiter must be one character other than newline or NUL"
            )
        datasets: dict[str, Dataset] = {}
        if bundle is not None:
            suffix = Path(bundle.filename or "").suffix.lower()
            kind = {
                ".json": "application/json",
                ".yaml": "application/yaml",
                ".yml": "application/yaml",
            }.get(suffix, "")
            datasets = _bundle(await bundle.read(), kind, limits)
        with tempfile.TemporaryDirectory(prefix="csv-", dir=path.parent) as scratch:
            for index, (name, upload) in enumerate(csvs):
                if name in datasets:
                    raise DataError("Duplicate dataset name")
                csv_path = Path(scratch) / str(index)
                with csv_path.open("wb") as target:
                    shutil.copyfileobj(upload.file, target, length=64 * 1024)
                datasets[name] = from_csv(
                    csv_path,
                    schema=template.datasets[name],
                    encoding=encoding,
                    delimiter=delimiter,
                    null_values=nulls,
                    limits=limits,
                )
        # bind(..., limits=limits) checks cumulative cells/text across all inputs.
        return datasets
    finally:
        await form.close()
