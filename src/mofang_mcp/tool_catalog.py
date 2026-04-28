from __future__ import annotations

from typing import Any


TOOL_VERSION = "0.1.0"


def tool(
    name: str,
    description: str,
    input_schema: dict[str, Any],
    *,
    version: str = TOOL_VERSION,
    deprecated: bool = False,
    sunset_at: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "tool_id": name,
        "version": version,
        "deprecated": deprecated,
        "sunset_at": sunset_at,
        "description": description,
        "inputSchema": input_schema,
    }


OPTIONS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "current": {"type": "integer", "minimum": 1, "maximum": 1000},
        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
    },
    "additionalProperties": False,
}


TOOLS: list[dict[str, Any]] = [
    tool(
        "route_query",
        "Route a natural language enterprise query to coarse modules.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    tool(
        "resolve_entity",
        "Resolve enterprise entities from multi-domain keywords and return standardized candidates. Supports business-info fields (company name, legal representative, unified credit code, registration number, address, members), recruitment, marketing, intellectual property, and bidding related terms.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "region_hint": {"type": "string"},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    tool(
        "company_snapshot",
        "Fetch a company snapshot for one or more modules.",
        {
            "type": "object",
            "properties": {
                "entity": {"type": "object"},
                "modules": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["profile", "risk", "bidding"]},
                },
                "options": OPTIONS_SCHEMA,
            },
            "required": ["entity", "modules"],
            "additionalProperties": False,
        },
    ),
    tool(
        "company_profile",
        "Fetch company profile information using company_snapshot with module=profile.",
        {
            "type": "object",
            "properties": {
                "entity": {"type": "object"},
                "options": OPTIONS_SCHEMA,
            },
            "required": ["entity"],
            "additionalProperties": False,
        },
    ),
    tool(
        "company_risk",
        "Fetch company risk and judicial information using company_snapshot with module=risk.",
        {
            "type": "object",
            "properties": {
                "entity": {"type": "object"},
                "options": OPTIONS_SCHEMA,
            },
            "required": ["entity"],
            "additionalProperties": False,
        },
    ),
    tool(
        "company_bidding",
        "Fetch company bidding information using company_snapshot with module=bidding.",
        {
            "type": "object",
            "properties": {
                "entity": {"type": "object"},
                "options": OPTIONS_SCHEMA,
            },
            "required": ["entity"],
            "additionalProperties": False,
        },
    ),
]


TOOL_BY_NAME = {item["name"]: item for item in TOOLS}
