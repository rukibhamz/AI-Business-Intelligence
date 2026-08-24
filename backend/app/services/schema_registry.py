from __future__ import annotations

import json
from typing import Any

from app.models import DataSource
from app.services.connectors import MySQLConnector, build_file_connector, build_mysql_connector
from app.services.schema_types import SourceSchema, schema_to_dict


def parse_connection_config(source: DataSource) -> dict[str, Any]:
    if not source.connection_config:
        return {}
    return json.loads(source.connection_config)


def get_connector(source: DataSource):
    config = parse_connection_config(source)
    if source.source_type == "file":
        return build_file_connector(config)
    if source.source_type == "mysql":
        return build_mysql_connector(config)
    raise ValueError(f"Unsupported source type: {source.source_type}")


async def introspect_source(source: DataSource) -> SourceSchema:
    connector = get_connector(source)
    return await connector.introspect()


async def preview_source_data(
    source: DataSource, *, table: str | None = None, limit: int = 100, offset: int = 0
) -> dict[str, Any]:
    connector = get_connector(source)
    return await connector.preview(table=table, limit=limit, offset=offset)


async def test_mysql_connection(config: dict[str, Any]) -> None:
    connector = MySQLConnector(config)
    await connector.test_connection()


def serialize_schema(schema: SourceSchema) -> str:
    return json.dumps(schema_to_dict(schema))
