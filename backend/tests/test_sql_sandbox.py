"""The sandbox is the boundary between generated SQL and the user's database."""

import pytest

from app.services.sql_sandbox import ensure_limit, strip_comments, validate_readonly_sql

ALLOWED = [
    "SELECT * FROM sales",
    "select revenue from sales where region = 'North'",
    "WITH t AS (SELECT 1 AS a) SELECT a FROM t",
    "SELECT region, SUM(revenue) AS revenue FROM sales GROUP BY region",
    "  SELECT 1  ;  ",
]

REJECTED = [
    # writes
    "DELETE FROM sales",
    "UPDATE sales SET revenue = 0",
    "INSERT INTO sales VALUES (1)",
    "DROP TABLE sales",
    "TRUNCATE TABLE sales",
    "ALTER TABLE sales ADD COLUMN x INT",
    "CREATE TABLE evil (id INT)",
    "GRANT ALL ON sales TO bob",
    # exfiltration / engine features
    "SELECT * FROM sales INTO OUTFILE '/tmp/x.csv'",
    "ATTACH DATABASE '/etc/passwd' AS pwn",
    "PRAGMA table_info(sales)",
    # A SELECT can be read-only and still be dangerous.
    "SELECT load_extension('evil.so')",
    "SELECT readfile('/etc/passwd')",
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT load_file('/etc/passwd')",
    "SELECT benchmark(100000000, md5('x'))",
    "SELECT pg_sleep(30)",
    "SELECT sleep(30)",
    # stacked statements
    "SELECT 1; DROP TABLE sales",
    "SELECT 1;DELETE FROM sales",
    # not a read
    "EXPLAIN SELECT * FROM sales",
    "",
    "   ",
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_allows_read_only_queries(sql):
    assert validate_readonly_sql(sql)


@pytest.mark.parametrize("sql", REJECTED)
def test_rejects_writes_and_stacked_statements(sql):
    with pytest.raises(ValueError):
        validate_readonly_sql(sql)


def test_comments_cannot_hide_a_second_statement():
    # Without comment stripping the ';' would be invisible to the validator.
    with pytest.raises(ValueError):
        validate_readonly_sql("SELECT 1 -- harmless\n; DROP TABLE sales")
    with pytest.raises(ValueError):
        validate_readonly_sql("SELECT 1 /* note */ ; DROP TABLE sales")


def test_comments_cannot_hide_a_forbidden_keyword():
    with pytest.raises(ValueError):
        validate_readonly_sql("SELECT * FROM sales /* x */ INTO OUTFILE 'f'")


def test_strip_comments_keeps_the_query():
    assert "SELECT 1" in strip_comments("SELECT 1 -- trailing note")


def test_ensure_limit_adds_a_cap():
    assert ensure_limit("SELECT * FROM sales", 50).endswith("LIMIT 50")


def test_ensure_limit_respects_an_existing_one():
    sql = "SELECT * FROM sales LIMIT 5"
    assert ensure_limit(sql, 200) == sql
