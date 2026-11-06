import json
from typing import Any

from cardreport import json_schema
from jsonschema import Draft202012Validator

from cardreport_server.openapi import component_schemas


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
