"""Bounded raw HTTP intake; no whole dataset parsing in API handlers."""

import asyncio
import re
from email.message import Message

from fastapi import Request
from starlette.requests import ClientDisconnect

from .errors import APIError


def media_type(request: Request, limit: int, *, multipart: bool = False) -> str:
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        raise APIError(
            415, "unsupported_encoding", "Compressed request bodies are not supported"
        )
    content_type = Message()
    content_type["content-type"] = request.headers.get("content-type", "")
    kind = content_type.get_content_type().lower()
    charset = content_type.get_content_charset("utf-8").lower()
    if multipart and kind == "multipart/form-data" and charset == "utf-8":
        boundaries = [
            value
            for key, value in (content_type.get_params() or [])[1:]
            if key == "boundary"
        ]
        if (
            len(boundaries) != 1
            or not isinstance(boundaries[0], str)
            or not re.fullmatch(r"[0-9A-Za-z'()+_,./:=? -]{1,70}", boundaries[0])
            or boundaries[0].endswith(" ")
        ):
            raise APIError(
                400, "invalid_multipart", "A valid multipart boundary is required"
            )
        kind = f'multipart/form-data; boundary="{boundaries[0]}"'
    elif kind not in {"application/json", "application/yaml"} or charset != "utf-8":
        raise APIError(
            415,
            "unsupported_media_type",
            "Use JSON/YAML with UTF-8"
            + (" or multipart/form-data" if multipart else ""),
        )
    length = request.headers.get("content-length")
    if length is not None:
        try:
            size = int(length)
            if size < 0:
                raise ValueError
        except ValueError:
            raise APIError(400, "invalid_length", "Invalid Content-Length") from None
        if size > limit:
            raise APIError(
                413, "input_too_large", "Request body exceeds its size limit"
            )
    return kind


async def read_template(request: Request) -> tuple[bytes, str]:
    limit = 1024 * 1024
    kind = media_type(request, limit)
    result = bytearray()
    try:
        async with asyncio.timeout(30):
            async for chunk in request.stream():
                if len(result) + len(chunk) > limit:
                    raise APIError(
                        413, "input_too_large", "Template exceeds its size limit"
                    )
                result.extend(chunk)
    except ClientDisconnect:
        raise APIError(
            400, "upload_interrupted", "Template upload interrupted"
        ) from None
    except TimeoutError:
        raise APIError(408, "upload_timeout", "Template upload timed out") from None
    return bytes(result), kind
