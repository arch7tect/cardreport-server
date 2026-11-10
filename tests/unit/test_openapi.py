import json
from typing import Any

from cardreport import json_schema
from jsonschema import Draft202012Validator

from cardreport_server.api import create_app
from cardreport_server.openapi import component_schemas
from cardreport_server.settings import Settings


def test_adaptation_preserves_validation(template_spec: dict[str, object]) -> None:
    schemas = component_schemas("template")
    wrapper: dict[str, Any] = {
        "$ref": "#/components/schemas/CardReportTemplate",
        "components": {"schemas": schemas},
    }
    original = Draft202012Validator(json.loads(json_schema("template")))
    adapted = Draft202012Validator(wrapper)
    for spec in (template_spec, {}, template_spec | {"unknown": 1}):
        assert original.is_valid(spec) == adapted.is_valid(spec)
    assert adapted.is_valid(template_spec)


def test_renderer_choices_are_documented(settings: Settings) -> None:
    parameters = create_app(settings).openapi()["paths"]["/v1/reports"]["post"][
        "parameters"
    ]
    renderer = next(item for item in parameters if item["name"] == "renderer")
    assert renderer["in"] == "query" and not renderer["required"]
    assert renderer["schema"]["enum"] == ["chromium", "weasyprint"]
    assert renderer["schema"]["default"] == "chromium"


def test_csv_multipart_is_only_on_reports(settings: Settings) -> None:
    paths = create_app(settings).openapi()["paths"]
    content = paths["/v1/reports"]["post"]["requestBody"]["content"]
    schema = content["multipart/form-data"]["schema"]
    assert schema["required"] == ["files"]
    assert schema["properties"]["files"]["items"]["format"] == "binary"
    assert schema["properties"]["csv_null"]["type"] == "array"
    assert "application/json" in content and "application/yaml" in content
    assert (
        "multipart/form-data"
        not in paths["/v1/templates/{template_id}/versions"]["post"]["requestBody"][
            "content"
        ]
    )


def test_layout_diagnostic_schema_is_derived_and_optional(settings: Settings) -> None:
    schema = create_app(settings).openapi()
    diagnostic = schema["components"]["schemas"]["LayoutDiagnostic"]
    assert set(diagnostic["required"]) == {"reason", "path"}
    assert diagnostic["additionalProperties"] is False
    assert "label_overlap" in diagnostic["properties"]["reason"]["enum"]
    status = schema["paths"]["/v1/reports/{report_id}"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    assert "error" in status["properties"]
