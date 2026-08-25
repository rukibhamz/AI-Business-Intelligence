from __future__ import annotations

import re

FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE|GRANT|REVOKE|"
    r"ATTACH|DETACH|PRAGMA|CALL|EXEC|EXECUTE|INTO|MERGE|LOAD|COPY)\b",
    re.IGNORECASE,
)


def validate_readonly_sql(sql: str) -> str:
    cleaned = sql.strip().rstrip(";").strip()
    if not cleaned:
        raise ValueError("Empty SQL")

    # Disallow multiple statements
    if ";" in cleaned:
        raise ValueError("Multiple SQL statements are not allowed")

    if FORBIDDEN.search(cleaned):
        raise ValueError("Only read-only SELECT queries are allowed")

    normalized = cleaned.lstrip("(").lstrip().upper()
    if not (normalized.startswith("SELECT") or normalized.startswith("WITH")):
        raise ValueError("Query must start with SELECT or WITH")

    return cleaned


def ensure_limit(sql: str, max_rows: int = 200) -> str:
    if re.search(r"\bLIMIT\s+\d+\b", sql, re.IGNORECASE):
        return sql
    return f"{sql} LIMIT {max_rows}"
