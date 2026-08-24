from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    status: str
    version: str = "0.1.0"
    environment: str


class DataSourceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    source_type: str = Field(..., pattern="^(file|mysql|postgres)$")
    connection_config: dict[str, Any] | None = None


class DataSourceUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    connection_config: dict[str, Any] | None = None


class DataSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    source_type: str
    connection_config: str | None
    schema_json: str | None
    created_at: datetime
    updated_at: datetime


class QueryCreate(BaseModel):
    data_source_id: int
    natural_language: str = Field(..., min_length=1)


class QueryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    data_source_id: int
    natural_language: str
    generated_sql: str | None
    status: str
    created_at: datetime
