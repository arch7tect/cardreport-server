from fastapi.testclient import TestClient

from cardreport_server.api import create_app
from cardreport_server.settings import Settings


def test_console_headers_and_routes(settings: Settings) -> None:
    client = TestClient(create_app(settings))
    redirect = client.get("/ui", follow_redirects=False)
    assert redirect.status_code == 307 and redirect.headers["location"].endswith("/ui/")
    page = client.get("/ui/")
    assert page.status_code == 200 and "CardReport" in page.text
    assert page.headers["cache-control"] == "no-cache"
    assert "unsafe-inline" not in page.headers["content-security-policy"]
    asset = client.get("/ui/app.js")
    assert asset.status_code == 200 and "javascript" in asset.headers["content-type"]
    cached = client.get("/ui/app.js", headers={"If-None-Match": asset.headers["etag"]})
    assert cached.status_code == 304 and cached.headers["cache-control"] == "no-cache"
    for path in ("/ui/missing.js", "/static/ui/index.html", "/v1/no-such-api"):
        assert client.get(path).status_code == 404
    swagger = client.get("/docs")
    assert swagger.status_code == 200
    assert "content-security-policy" not in swagger.headers
