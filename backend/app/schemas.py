from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    status: str
    version: str = "0.1.0"
    environment: str


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3)
    password: str = Field(..., min_length=4)


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3)
    password: str = Field(..., min_length=4)
    full_name: str | None = None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str | None
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


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


class MySQLConnectionConfig(BaseModel):
    host: str = "localhost"
    port: int = 3306
    user: str = "root"
    password: str = ""
    database: str = Field(..., min_length=1)


class MySQLSourceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    connection_config: MySQLConnectionConfig


class PreviewResponse(BaseModel):
    table: str | None
    columns: list[str]
    rows: list[dict[str, Any]]
    limit: int
    offset: int
    total: int


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
