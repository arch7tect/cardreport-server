"""Structural input extraction shared by downloads and the isolated decoder."""

import asyncio
import hashlib
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from cardreport import DataError, DataLimits
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from starlette.datastructures import Headers
from starlette.formparsers import MultiPartException, MultiPartParser


@dataclass(frozen=True)
class InputFile:
    id: int
    name: str
    part: str
    content: bytes

    def describe(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "part": self.part,
            "format": Path(self.name).suffix.lower().lstrip("."),
            "size": len(self.content),
            "sha256": hashlib.sha256(self.content).hexdigest(),
        }


@dataclass(frozen=True)
class InputFiles:
    files: list[InputFile]
    fields: list[tuple[str, str]]


class FileResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: int = Field(ge=1, le=32)
    status: Literal["parsed", "failed", "skipped"] = "skipped"
    datasets: list[str] = Field(default_factory=list, max_length=32)
    error: Literal["invalid_file", "duplicate_dataset"] | None = None


RESULTS = TypeAdapter(list[FileResult])


class CompleteMultipartParser(MultiPartParser):
    complete = False

    def on_end(self) -> None:
        self.complete = True


def extract_parts(path: Path, content_type: str) -> InputFiles:
    if path.stat().st_size > DataLimits().max_json_bytes:
        raise DataError("Input exceeds its size limit")
    if content_type.startswith("multipart/form-data;"):
        return asyncio.run(_extract(path, content_type))
    suffix = {"application/json": "json", "application/yaml": "yaml"}.get(content_type)
    if suffix is None:
        raise DataError("Unsupported input type")
    return InputFiles([InputFile(1, "input." + suffix, "files", path.read_bytes())], [])


async def _extract(path: Path, content_type: str) -> InputFiles:
    async def chunks() -> AsyncGenerator[bytes, None]:
        with path.open("rb") as stream:
            while chunk := stream.read(64 * 1024):
                yield chunk
        # Raise inside Starlette's parse loop to close unfinished spooled files.
        if not parser.complete:
            raise MultiPartException("Incomplete multipart body")

    parser = CompleteMultipartParser(
        Headers({"Content-Type": content_type}),
        chunks(),
        max_files=32,
        max_fields=34,
        max_part_size=1024,
    )
    try:
        form = await parser.parse()
    except (MultiPartException, ValueError):
        raise DataError("Invalid multipart input") from None
    try:
        # Bound catalog/ZIP metadata expansion, including malicious MIME headers.
        metadata_size = sum(
            len(key.encode("utf-8"))
            + len(
                (value if isinstance(value, str) else value.filename or "").encode(
                    "utf-8"
                )
            )
            for key, value in form.multi_items()
        )
        if metadata_size > 64 * 1024:
            raise DataError("Input file metadata exceeds its size limit")
        files: list[InputFile] = []
        fields = []
        for key, value in form.multi_items():
            if isinstance(value, str):
                fields.append((key, value))
            else:
                files.append(
                    InputFile(
                        len(files) + 1, value.filename or "", key, await value.read()
                    )
                )
        return InputFiles(files, fields)
    finally:
        await form.close()


def read_results(directory: Path, content_type: str) -> list[dict[str, object]] | None:
    path = directory / "files.json"
    if not path.exists():
        return None
    if path.stat().st_size > 64 * 1024:
        raise ValueError("File diagnostics exceed their size limit")
    results = RESULTS.validate_json(path.read_bytes())
    try:
        count = len(extract_parts(directory / "input", content_type).files)
    except DataError:
        count = 0
    if [r.id for r in results] != list(range(1, count + 1)):
        raise ValueError("File diagnostics do not match the original upload")
    if any(len(name) > 100 for r in results for name in r.datasets):
        raise ValueError("Dataset name exceeds its size limit")
    return [r.model_dump() for r in results]
