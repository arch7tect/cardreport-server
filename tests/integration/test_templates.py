import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import uuid4

import pytest
from cardreport import ReportTemplate
from fastapi.testclient import TestClient

from cardreport_server.api import create_app
from cardreport_server.db import Database
from cardreport_server.settings import Settings
from cardreport_server.templates import register

pytestmark = pytest.mark.integration


def test_template_lifecycle(
    integration_settings: Settings, template_spec: dict[str, object]
) -> None:
    slug = "template-" + uuid4().hex
    with TestClient(create_app(integration_settings)) as client:
        route = f"/v1/templates/{slug}"
        first = client.post(route + "/versions", json=template_spec)
        assert first.status_code == 201, first.text
        assert first.json()["version"] == 1
        yaml_text = ReportTemplate.from_dict(template_spec).to_yaml()
        second = client.post(
            route + "/versions",
            content=yaml_text,
            headers={"Content-Type": "application/yaml"},
        )
        assert second.status_code == 201
        assert second.json()["digest"] == first.json()["digest"]
        saved = client.get(route + "/versions/1").json()["definition"]
        assert saved == ReportTemplate.from_dict(template_spec).to_dict()
        assert (
            hashlib.sha256(
                ReportTemplate.from_dict(saved).to_json().encode()
            ).hexdigest()
            == first.json()["digest"]
        )
        page = client.get(route + "/versions", params={"limit": 1}).json()
        assert page["next"] == 1
        assert (
            client.get(route + "/versions", params={"after": 1}).json()["items"][0][
                "version"
            ]
            == 2
        )
        assert client.patch(route, json={"archived": True}).status_code == 200
        assert client.post(route + "/versions", json=template_spec).status_code == 409
        assert client.get(route + "/versions/1").json()["definition"] == saved
        assert client.patch(route, json={"archived": False}).status_code == 200
        assert (
            client.post(route + "/versions", json=template_spec).json()["version"] == 3
        )
        assert client.get(route + "/versions/500").status_code == 404
        assert client.get("/v1/templates/missing").status_code == 404
        assert client.patch(route, json={"archived": "false"}).status_code == 422


def test_concurrent_versions(
    database: Database, template_spec: dict[str, object]
) -> None:
    slug = "race-" + uuid4().hex
    data = json.dumps(template_spec).encode()
    with ThreadPoolExecutor(max_workers=6) as pool:
        versions = list(
            pool.map(
                lambda _: register(database, slug, data, "application/json")["version"],
                range(12),
            )
        )
    assert sorted(versions) == list(range(1, 13))


@pytest.mark.parametrize(
    "body,headers,status",
    [
        (b"{}", {"Content-Type": "application/json"}, 422),
        (b'{"format":"a","format":"b"}', {"Content-Type": "application/json"}, 422),
        (b"{}", {"Content-Type": "text/plain"}, 415),
        (b"{}", {"Content-Type": "application/json;charset=utf-16"}, 415),
        (b"{}", {"Content-Type": "application/json", "Content-Encoding": "gzip"}, 415),
        (b"x" * (1024 * 1024 + 1), {"Content-Type": "application/json"}, 413),
    ],
)
def test_bad_templates(
    integration_settings: Settings, body: bytes, headers: dict[str, str], status: int
) -> None:
    with TestClient(create_app(integration_settings)) as client:
        result = client.post(
            "/v1/templates/bad/versions", content=body, headers=headers
        )
        assert result.status_code == status
        assert "error" in result.json()


def test_offline_docs_and_schema(integration_settings: Settings) -> None:
    with TestClient(create_app(integration_settings)) as client:
        response = client.get("/docs")
        assert response.status_code == 200
        assert 'src="https://' not in response.text
        assert 'href="https://' not in response.text
        assert client.get("/static/swagger-ui-bundle.js").status_code == 200
        assert client.get("/static/swagger-ui.css").status_code == 200
        schema = client.get("/openapi.json").json()

        def verify(node: Any) -> None:
            if isinstance(node, dict):
                if "$ref" in node:
                    assert node["$ref"].startswith("#/")
                    target = schema
                    for part in node["$ref"][2:].split("/"):
                        target = target[part.replace("~1", "/").replace("~0", "~")]
                for value in node.values():
                    verify(value)
            elif isinstance(node, list):
                for value in node:
                    verify(value)

        verify(schema)
        content = schema["paths"]["/v1/templates/{template_id}/versions"]["post"][
            "requestBody"
        ]["content"]
        assert set(content) == {"application/json", "application/yaml"}
        preflight = client.options(
            "/v1/templates",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert "access-control-allow-origin" not in preflight.headers


@pytest.mark.parametrize(
    "page,dimensions",
    [
        ({}, [210, 297]),
        ({"size": "A3", "orientation": "landscape"}, [420, 297]),
        ({"size": [564.444, 423.333]}, [564.444, 423.333]),
    ],
)
def test_template_page_dimensions(
    integration_settings: Settings,
    template_spec: dict[str, Any],
    page: dict[str, Any],
    dimensions: list[float],
) -> None:
    template_spec["report"]["page"] = page
    slug = "dimensions-" + uuid4().hex
    with TestClient(create_app(integration_settings)) as client:
        created = client.post(f"/v1/templates/{slug}/versions", json=template_spec)
        assert created.status_code == 201
        stored = client.get(f"/v1/templates/{slug}/versions/1").json()
        assert stored["page_dimensions_mm"] == dimensions
        assert stored["definition"] == template_spec
        assert stored["digest"] == created.json()["digest"]


def test_template_search_and_pagination(
    integration_settings: Settings, template_spec: dict[str, Any]
) -> None:
    prefix = "search-" + uuid4().hex
    ids = [prefix + suffix for suffix in ("-a", "-b", "-c")]
    with TestClient(create_app(integration_settings)) as client:
        for index, slug in enumerate(ids):
            template_spec["report"]["title"] = f"{prefix} Revenue {index}"
            assert (
                client.post(
                    f"/v1/templates/{slug}/versions", json=template_spec
                ).status_code
                == 201
            )
        template_spec["report"]["title"] = f"{prefix} Budget 100% _ \\ <b>"
        assert (
            client.post(
                f"/v1/templates/{ids[0]}/versions", json=template_spec
            ).status_code
            == 201
        )
        assert (
            client.patch(f"/v1/templates/{ids[2]}", json={"archived": True}).status_code
            == 200
        )

        params = {"q": "  " + prefix.upper() + "  ", "limit": 1, "archived": "false"}
        first = client.get("/v1/templates", params=params).json()
        assert [row["id"] for row in first["items"]] == ids[:1]
        assert first["items"][0]["title"] == template_spec["report"]["title"]
        second = client.get(
            "/v1/templates", params=params | {"after": first["next"]}
        ).json()
        assert [row["id"] for row in second["items"]] == ids[1:2]
        assert second["next"] is None
        assert client.get("/v1/templates", params=params).json() == first

        def matches(query: str, **filters: str) -> list[str]:
            response = client.get("/v1/templates", params={"q": query, **filters})
            assert response.status_code == 200, response.text
            return [row["id"] for row in response.json()["items"]]

        assert matches(prefix + " rEvEnUe") == ids[1:]
        assert matches(prefix + " Revenue", archived="false") == ids[1:2]
        assert matches(prefix, archived="true") == ids[2:]
        assert matches(prefix + " Budget 100% _ \\ <b>") == ids[:1]
        assert matches(prefix + " Budget 100_") == []
        assert matches(prefix + " missing") == []
        assert matches(ids[0].upper()) == ids[:1]
        assert client.get("/v1/templates", params={"q": "x" * 201}).status_code == 422
