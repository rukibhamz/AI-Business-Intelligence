"""Guardrail between generated SQL and the user's database.

Generated SQL is never trusted: it may come from a language model, and the
model's context includes column names taken from user-uploaded files. Only a
single read-only statement is allowed through.
"""

from __future__ import annotations

import re

# Keywords that mutate data, change schema, or reach the filesystem. Keywords
# that can only ever begin a statement (BEGIN, COMMIT, USE, VACUUM…) are not
# listed: stacked statements are rejected outright and the query must already
# start with SELECT or WITH, so listing them only risks rejecting a column that
# happens to share the name.
FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE|GRANT|REVOKE|"
    r"ATTACH|DETACH|PRAGMA|CALL|EXEC|EXECUTE|INTO|MERGE|LOAD|COPY)\b",
    re.IGNORECASE,
)

# Functions that read files, load code, or stall the server. A SELECT can be
# read-only and still be dangerous — SQLite's load_extension() runs native code.
FORBIDDEN_FUNCTIONS = re.compile(
    r"\b("
    # SQLite
    r"load_extension|readfile|writefile|edit|fts3_tokenizer|sqlite_compileoption_used|"
    # MySQL
    r"load_file|benchmark|sleep|sys_exec|sys_eval|master_pos_wait|"
    # PostgreSQL
    r"pg_read_file|pg_read_binary_file|pg_ls_dir|pg_sleep|pg_stat_file|dblink|"
    r"lo_import|lo_export|query_to_xml"
    r")\s*\(",
    re.IGNORECASE,
)

_LINE_COMMENT = re.compile(r"--[^\r\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def strip_comments(sql: str) -> str:
    """Remove SQL comments so they cannot mask a forbidden keyword."""
    return _BLOCK_COMMENT.sub(" ", _LINE_COMMENT.sub(" ", sql))


def validate_readonly_sql(sql: str) -> str:
    """Return the statement if it is a single read-only query, else raise."""
    cleaned = strip_comments(sql).strip().rstrip(";").strip()
    if not cleaned:
        raise ValueError("Empty SQL")

    if ";" in cleaned:
        raise ValueError("Multiple SQL statements are not allowed")

    if FORBIDDEN.search(cleaned):
        raise ValueError("Only read-only SELECT queries are allowed")

    if FORBIDDEN_FUNCTIONS.search(cleaned):
        raise ValueError("That query uses a function that is not permitted")

    normalized = cleaned.lstrip("(").lstrip().upper()
    if not (normalized.startswith("SELECT") or normalized.startswith("WITH")):
        raise ValueError("Query must start with SELECT or WITH")

    return cleaned


def ensure_limit(sql: str, max_rows: int = 200) -> str:
    if re.search(r"\bLIMIT\s+\d+\b", sql, re.IGNORECASE):
        return sql
    return f"{sql} LIMIT {max_rows}"
