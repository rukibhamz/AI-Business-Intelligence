from __future__ import annotations

import csv
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import httpx

from app.config import settings
from app.models import DataSource
from app.services.schema_context import build_schema_prompt, heuristic_sql
from app.services.schema_registry import parse_connection_config
from app.services.sql_sandbox import ensure_limit, validate_readonly_sql


SYSTEM_PROMPT = """You are a SQL expert for a business intelligence tool.
Given a database schema and a user question, return ONLY a single read-only SQL query.
Rules:
- SELECT or WITH only. No writes, DDL, or multiple statements.
- Use only tables/columns from the schema.
- Prefer LIMIT 50 unless the user asks for a specific limit.
- For MySQL, use backticks for identifiers when needed.
- Do not wrap the SQL in markdown fences.
"""


async def generate_sql(
    source: DataSource,
    question: str,
    *,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> tuple[str, str]:
    """Returns (sql, mode) where mode is 'openai' or 'heuristic'."""
    key = api_key if api_key is not None else settings.openai_api_key
    mdl = model or settings.openai_model
    url = base_url or settings.openai_base_url

    if key:
        sql = await _openai_sql(source, question, api_key=key, model=mdl, base_url=url)
        return sql, "openai"

    sql = heuristic_sql(source, question)
    if not sql:
        raise ValueError(
            "No OpenAI API key configured and could not build a heuristic query. "
            "Set it in Settings or OPENAI_API_KEY in .env"
        )
    return sql, "heuristic"


async def _openai_sql(
    source: DataSource,
    question: str,
    *,
    api_key: str,
    model: str,
    base_url: str,
) -> str:
    schema_text = build_schema_prompt(source)
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"{schema_text}\n\nQuestion: {question}\n\nSQL:",
            },
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        res = await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
        )
        res.raise_for_status()
        data = res.json()

    content = data["choices"][0]["message"]["content"].strip()
    content = re.sub(r"^```(?:sql)?\s*", "", content, flags=re.IGNORECASE)
    content = re.sub(r"\s*```$", "", content)
    return content.strip()


async def execute_sql(source: DataSource, sql: str, *, max_rows: int = 200) -> dict[str, Any]:
    safe = validate_readonly_sql(sql)
    safe = ensure_limit(safe, max_rows)

    if source.source_type == "mysql":
        return await _exec_mysql(source, safe)
    if source.source_type == "file":
        return _exec_file_sqlite(source, safe)
    raise ValueError(f"Unsupported source type for queries: {source.source_type}")


async def _exec_mysql(source: DataSource, sql: str) -> dict[str, Any]:
    import aiomysql

    config = parse_connection_config(source)
    conn = await aiomysql.connect(
        host=config.get("host", "localhost"),
        port=int(config.get("port", 3306)),
        user=config.get("user", "root"),
        password=config.get("password", ""),
        db=config.get("database"),
    )
    try:
        async with conn.cursor() as cur:
            await cur.execute(sql)
            rows_raw = await cur.fetchall()
            columns = [d[0] for d in (cur.description or [])]
            rows = [dict(zip(columns, row)) for row in rows_raw]
            # Serialize non-JSON types
            for row in rows:
                for k, v in list(row.items()):
                    if hasattr(v, "isoformat"):
                        row[k] = v.isoformat()
                    elif isinstance(v, (bytes, bytearray)):
                        row[k] = v.decode("utf-8", errors="replace")
    finally:
        conn.close()

    return {"columns": columns, "rows": rows, "sql": sql}


def _exec_file_sqlite(source: DataSource, sql: str) -> dict[str, Any]:
    config = parse_connection_config(source)
    path = Path(config["file_path"])
    if not path.exists():
        raise ValueError("Source file not found on disk")

    table = Path(config.get("original_name", path.name)).stem
    table = re.sub(r"[^A-Za-z0-9_]", "_", table) or "data"
    if table[0].isdigit():
        table = f"t_{table}"

    conn = sqlite3.connect(":memory:")
    try:
        if config.get("format") == "xlsx":
            _load_xlsx_into_sqlite(conn, path, table)
        else:
            _load_csv_into_sqlite(conn, path, table)

        # Rewrite common original table names to sanitized name
        rewritten = sql
        original = Path(config.get("original_name", path.name)).stem
        if original and original != table:
            rewritten = re.sub(
                rf"(?i)`?{re.escape(original)}`?",
                f"`{table}`",
                rewritten,
            )

        cur = conn.execute(rewritten)
        rows_raw = cur.fetchall()
        columns = [d[0] for d in (cur.description or [])]
        rows = [dict(zip(columns, row)) for row in rows_raw]
    finally:
        conn.close()

    return {"columns": columns, "rows": rows, "sql": sql}


def _load_csv_into_sqlite(conn: sqlite3.Connection, path: Path, table: str) -> None:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if not header:
            raise ValueError("CSV has no header row")
        cols = [_safe_col(h, i) for i, h in enumerate(header)]
        raw_rows: list[list[str]] = []
        for row in reader:
            padded = (row + [""] * len(cols))[: len(cols)]
            raw_rows.append(padded)
        _insert_typed_rows(conn, table, cols, raw_rows)


def _load_xlsx_into_sqlite(conn: sqlite3.Connection, path: Path, table: str) -> None:
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    header = next(rows_iter, None)
    if not header:
        wb.close()
        raise ValueError("Excel sheet has no header row")
    cols = [_safe_col(str(h) if h is not None else "", i) for i, h in enumerate(header)]
    raw_rows: list[list[str]] = []
    for row in rows_iter:
        padded = []
        for i in range(len(cols)):
            val = row[i] if i < len(row) else None
            padded.append("" if val is None else str(val))
        raw_rows.append(padded)
    wb.close()
    _insert_typed_rows(conn, table, cols, raw_rows)


def _insert_typed_rows(
    conn: sqlite3.Connection,
    table: str,
    cols: list[str],
    raw_rows: list[list[str]],
) -> None:
    """Infer REAL vs TEXT per column so ORDER BY works on numeric CSV fields."""
    types = [_infer_sqlite_type(raw_rows, i) for i in range(len(cols))]
    col_defs = ", ".join(f"`{c}` {t}" for c, t in zip(cols, types))
    conn.execute(f"CREATE TABLE `{table}` ({col_defs})")
    placeholders = ", ".join("?" for _ in cols)
    typed_rows: list[list[Any]] = []
    for row in raw_rows:
        typed: list[Any] = []
        for i, val in enumerate(row):
            if types[i] == "REAL":
                typed.append(None if val == "" else float(val.replace(",", "")))
            else:
                typed.append(val)
        typed_rows.append(typed)
    conn.executemany(f"INSERT INTO `{table}` VALUES ({placeholders})", typed_rows)
    conn.commit()


def _infer_sqlite_type(rows: list[list[str]], col_index: int) -> str:
    seen = False
    for row in rows:
        val = row[col_index].strip() if col_index < len(row) else ""
        if val == "":
            continue
        seen = True
        if not re.fullmatch(r"-?\d+(?:\.\d+)?", val.replace(",", "")):
            return "TEXT"
    return "REAL" if seen else "TEXT"


def _safe_col(name: str, index: int) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", name.strip()) or f"column_{index + 1}"
    if cleaned[0].isdigit():
        cleaned = f"c_{cleaned}"
    return cleaned


def pack_result(result: dict[str, Any]) -> str:
    return json.dumps(result, default=str)
