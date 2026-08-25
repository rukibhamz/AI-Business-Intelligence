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
    field_mapping: dict[str, str] | None = None
    mapping_status: str | None = None
    row_count: int | None = None


class FieldMappingUpdate(BaseModel):
    field_mapping: dict[str, str]
    confirm: bool = True


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
    """Ask a question against the workspace. Optional source pins to one dataset."""

    natural_language: str = Field(..., min_length=1)
    data_source_id: int | None = None
    # Groups the questions asked in one sitting.
    session_id: str | None = Field(None, max_length=64)


class QueryResultPayload(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    sql: str | None = None


class ChartRecommendation(BaseModel):
    type: str
    label_key: str | None = None
    value_keys: list[str] = []
    reason: str | None = None


class QueryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    data_source_id: int
    natural_language: str
    generated_sql: str | None
    status: str
    created_at: datetime
    result: QueryResultPayload | None = None
    explanation: str | None = None
    mode: str | None = None
    chart: ChartRecommendation | None = None
    session_id: str | None = None
    #: Plain-language answer grounded in the returned rows.
    answer: str | None = None
    #: How the UI should present this answer.
    response_format: str | None = None


class QueryRunResponse(QueryResponse):
    pass


class DashboardWidgetPayload(BaseModel):
    id: str
    query_id: int
    title: str
    chart_type: str = "bar"


class DashboardWidgetCreate(BaseModel):
    query_id: int
    title: str | None = None
    chart_type: str | None = None


class DashboardCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class DashboardUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    layout_json: dict | None = None


class DashboardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    layout_json: str | None
    widgets: list[DashboardWidgetPayload] = []
    created_at: datetime
    updated_at: datetime


class ColorSchemeOption(BaseModel):
    id: str
    primary: str
    primary_container: str
    secondary: str
    secondary_container: str
    label: str


class AppSettingsPublic(BaseModel):
    llm_provider: str
    openai_model: str
    openai_base_url: str
    api_key_set: bool
    api_key_masked: str | None = None
    platform_name: str
    platform_tagline: str
    logo_url: str | None = None
    color_scheme: str
    color_schemes: list[ColorSchemeOption] = []
    providers: list[str] = []


class AppSettingsUpdate(BaseModel):
    llm_provider: str | None = None
    openai_model: str | None = None
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    platform_name: str | None = Field(None, min_length=1, max_length=80)
    platform_tagline: str | None = Field(None, max_length=120)
    color_scheme: str | None = None


class ConnectionTestRequest(BaseModel):
    llm_provider: str | None = None
    openai_model: str | None = None
    openai_api_key: str | None = None
    openai_base_url: str | None = None


class ConnectionTestResponse(BaseModel):
    ok: bool
    message: str


class SourceSummary(BaseModel):
    id: int
    name: str
    source_type: str
    mapping_status: str | None = None
    row_count: int | None = None
    analyzable: bool = False


class OverviewSourceMeta(BaseModel):
    id: int
    name: str
    source_type: str
    rows_analyzed: int
    total_rows: int
    truncated: bool


class KpiCard(BaseModel):
    id: str
    label: str
    value: Any
    format: str
    delta_pct: float | None = None
    direction: str | None = None
    tone: str | None = None
    caption: str | None = None


class OverviewChart(BaseModel):
    id: str
    title: str
    type: str
    label_key: str
    value_keys: list[str]
    data: list[dict[str, Any]]
    format: str = "number"


class CoverageReport(BaseModel):
    mapped: list[str] = []
    missing: list[str] = []
    unmapped_columns: list[str] = []


class PeriodMeta(BaseModel):
    granularity: str | None = None
    start: str | None = None
    end: str | None = None
    buckets: int = 0


class OverviewResponse(BaseModel):
    generated_at: str
    source: OverviewSourceMeta | None = None
    available_sources: list[SourceSummary] = []
    kpis: list[KpiCard] = []
    charts: list[OverviewChart] = []
    coverage: CoverageReport | None = None
    notices: list[str] = []
    period: PeriodMeta | None = None
    error: str | None = None


class Finding(BaseModel):
    id: str
    severity: str
    title: str
    body: str
    action: str
    context: str
    metric: str | None = None
    source_id: int | None = None
    source_name: str | None = None


class FindingsResponse(BaseModel):
    generated_at: str
    findings: list[Finding] = []
    available_sources: list[SourceSummary] = []
    errors: list[str] = []
