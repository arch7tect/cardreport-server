"""Static console assets with headers scoped away from Swagger and report output."""

from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope


class ConsoleFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers.update(
            {
                "Cache-Control": "no-cache",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": (
                    "default-src 'none'; script-src 'self'; style-src 'self'; "
                    "img-src 'self' data:; connect-src 'self'; frame-src 'self'; "
                    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
                ),
            }
        )
        return response
