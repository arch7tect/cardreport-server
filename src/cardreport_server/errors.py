"""Stable public errors, independent of library exception text."""

from typing import Any


class APIError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        location: dict[str, Any] | None = None,
    ) -> None:
        self.status = status
        self.code = code
        self.message = message
        self.location = location or {}
        super().__init__(code)

    def body(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                **({"location": self.location} if self.location else {}),
            }
        }
