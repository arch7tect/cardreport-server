"""Adapt packaged CardReport schemas for OpenAPI without duplicating them."""

import json
from typing import Any, Literal

from cardreport import json_schema
from fastapi import FastAPI


def component_schemas(kind: Literal["template", "data"]) -> dict[str, Any]:
    document = json.loads(json_schema(kind))
    prefix = "CardReport" + kind.title()
    definitions = document.pop("$defs", {})

    def rewrite(value: Any) -> Any:
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        if not isinstance(value, dict):
            return value
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"$id", "$schema"}:
                continue
            if key == "$ref":
                if item.startswith("#/$defs/"):
                    item = "#/components/schemas/" + prefix + "_" + item[8:]
                elif item == "#":
                    item = "#/components/schemas/" + prefix
                else:
                    raise RuntimeError("Unsupported packaged schema reference")
            result[key] = rewrite(item)
        return result

    return {
        prefix: rewrite(document),
        **{prefix + "_" + name: rewrite(value) for name, value in definitions.items()},
    }


def request_schema(kind: Literal["template", "data"]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "requestBody": {
            "required": True,
            "content": {
                media: {
                    "schema": {"$ref": "#/components/schemas/CardReport" + kind.title()}
                }
                for media in ("application/json", "application/yaml")
            },
        }
    }

    if kind == "data":
        result["requestBody"]["content"]["multipart/form-data"] = {
            "schema": {
                "type": "object",
                "required": ["files"],
                "additionalProperties": False,
                "properties": {
                    "files": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 32,
                        "items": {"type": "string", "format": "binary"},
                        "description": "JSON/YAML bundles and CSV files in any combination. CSV stems name template datasets; bundles contain their own names.",
                    },
                    "csv_encoding": {"type": "string", "default": "utf-8"},
                    "csv_delimiter": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 1,
                        "default": ",",
                    },
                    "csv_null": {
                        "type": "array",
                        "maxItems": 32,
                        "items": {"type": "string"},
                        "description": "Exact null tokens, including an empty string if desired. Omitted means no tokens.",
                    },
                },
            },
            "encoding": {
                "files": {"style": "form", "explode": True},
                "csv_null": {"style": "form", "explode": True},
            },
        }
    return result


def install_schemas(app: FastAPI) -> None:
    schema = app.openapi()
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    components.update(component_schemas("template"))
    components.update(component_schemas("data"))
    app.openapi_schema = schema
