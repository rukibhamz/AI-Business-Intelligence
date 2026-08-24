from __future__ import annotations

from typing import Any, TypedDict


class ColumnSchema(TypedDict):
    name: str
    type: str


class TableSchema(TypedDict):
    name: str
    columns: list[ColumnSchema]


class SourceSchema(TypedDict):
    tables: list[TableSchema]


def schema_to_dict(schema: SourceSchema) -> dict[str, Any]:
    return {"tables": schema["tables"]}


def parse_schema_json(raw: str | None) -> SourceSchema | None:
    if not raw:
        return None
    import json

    data = json.loads(raw)
    return {"tables": data.get("tables", [])}
