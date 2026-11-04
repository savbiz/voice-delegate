"""Review untrusted MCP server data before the worker can use it.

Tool schemas, descriptions and results come from a server the application does not trust.
This module accepts only flat, bounded schemas, strips control characters and turns tool
output into verifiable cited sources.
"""

import hashlib
import re
import unicodedata
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, create_model

from .reference import Source

if TYPE_CHECKING:
    from .mcp import McpServer

FIELD_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,31}")
DESCRIPTION_BYTES = 512
MAX_PROPERTIES = 8
STRING_LIMIT = 500
SOURCE_TEXT = 400


def clean(value: str, limit: int) -> str:
    return " ".join(
        "".join(" " if unicodedata.category(c).startswith("C") else c for c in value).split()
    )[:limit].rstrip()


def parameters_model(name: str, schema: object) -> type[BaseModel] | None:
    """Accept only a flat object of scalar properties; reject everything else.

    Nested objects, arrays, references and unions are refused rather than approximated, so
    the application can validate every argument before it leaves the process.
    """
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return None
    if not set(schema) <= {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "title",
        "description",
        "$schema",
    }:
        return None
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    if (
        not isinstance(properties, dict)
        or len(properties) > MAX_PROPERTIES
        or not isinstance(required, list)
        or not set(required) <= set(properties)
        or any(not isinstance(key, str) or FIELD_NAME.fullmatch(key) is None for key in properties)
    ):
        return None
    fields: dict[str, Any] = {}
    kinds: dict[str, type] = {"string": str, "integer": int, "number": float, "boolean": bool}
    for key, spec in properties.items():
        if not isinstance(spec, dict) or spec.get("type") not in kinds:
            return None
        if not set(spec) <= {
            "type",
            "description",
            "enum",
            "minimum",
            "maximum",
            "maxLength",
            "default",
            "title",
        }:
            return None
        kind: Any = kinds[spec["type"]]
        options: dict[str, Any] = {}
        if spec["type"] == "string":
            limit = spec.get("maxLength", STRING_LIMIT)
            if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
                return None
            options["max_length"] = min(limit, STRING_LIMIT)
            enum = spec.get("enum")
            if enum is not None:
                if (
                    not isinstance(enum, list)
                    or not 1 <= len(enum) <= 16
                    or any(not isinstance(v, str) or len(v) > 64 for v in enum)
                ):
                    return None
                kind = Literal[tuple(enum)]
                options.pop("max_length")
        elif spec["type"] in {"integer", "number"}:
            for bound, option in (("minimum", "ge"), ("maximum", "le")):
                if bound in spec:
                    value = spec[bound]
                    if isinstance(value, bool) or not isinstance(value, (int, float)):
                        return None
                    options[option] = value
        description = spec.get("description")
        if isinstance(description, str):
            options["description"] = clean(description, 160)
        fields[key] = (
            (kind, Field(..., **options))
            if key in required
            else (kind | None, Field(None, **options))
        )
    return create_model(
        "Args_" + re.sub(r"\W", "_", name), __config__=ConfigDict(extra="forbid"), **fields
    )


def mcp_source(server: str, tool: str, text: str) -> Source | None:
    text = clean(text, SOURCE_TEXT)
    if not text:
        return None
    path = f"mcp://{server}/{tool}"
    digest = hashlib.sha256(text.encode()).hexdigest()
    return Source(
        id="mcp-" + hashlib.sha256((path + "\0" + digest).encode()).hexdigest()[:32],
        title=f"{tool} ({server})"[:160],
        path=path,
        section="MCP tool",
        text=text,
        digest=digest,
    )


def verified_mcp_source(source: Source) -> bool:
    if not all(isinstance(v, str) for v in asdict(source).values()):
        return False
    target = urlsplit(source.path)
    tool = target.path.removeprefix("/")
    candidate = mcp_source(target.hostname or "", tool, source.text)
    return target.scheme == "mcp" and candidate == source


def review_tools(
    server: "McpServer", raw: list[dict[str, Any]]
) -> dict[str, tuple[str, type[BaseModel]]]:
    """Keep only allowlisted, uniquely named tools with reviewable schemas.

    `readOnlyHint` can never authorize a tool the operator did not list, but an explicit
    `readOnlyHint: false` on a listed tool excludes it.
    """
    names = [entry.get("name") for entry in raw]
    kept: dict[str, tuple[str, type[BaseModel]]] = {}
    for entry in raw:
        name = entry.get("name")
        if (
            not isinstance(name, str)
            or name not in server.tools
            or names.count(name) != 1
            or not isinstance(entry.get("description", ""), str)
        ):
            continue
        annotations = entry.get("annotations")
        if isinstance(annotations, dict) and annotations.get("readOnlyHint") is False:
            continue
        model = parameters_model(f"{server.id}_{name}", entry.get("inputSchema"))
        if model is None:
            continue
        description = entry.get("description", "")
        kept[name] = (clean(description, DESCRIPTION_BYTES), model)
    return kept
