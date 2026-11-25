"""AST-based SQL security guardrail using SQLGlot (Postgres dialect)."""

from __future__ import annotations

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

DEFAULT_LIMIT = 100
MAX_LIMIT = 1000

FORBIDDEN_FUNCTIONS = frozenset(
    {
        "pg_sleep",
        "pg_read_file",
        "pg_read_binary_file",
        "pg_ls_dir",
        "lo_import",
        "lo_export",
        "dblink",
        "dblink_exec",
        "dblink_connect",
        "pg_terminate_backend",
        "pg_cancel_backend",
    }
)

FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Alter,
    exp.Create,
    exp.Command,
    exp.Grant,
    exp.Revoke,
    exp.Copy,
    exp.TruncateTable,
    exp.Into,
    exp.Lock,
)


class SQLGuardError(ValueError):
    """Raised when generated SQL fails AST safety validation."""


def _validate_limits(stmt: exp.Expression, max_limit: int) -> None:
    """Ensure every LIMIT node uses a non-negative integer <= max_limit."""
    for limit_node in stmt.find_all(exp.Limit):
        expr = limit_node.expression
        if not isinstance(expr, exp.Literal) or expr.is_string:
            raise SQLGuardError(f"Non-numeric LIMIT is forbidden: {limit_node.sql(dialect='postgres')}")
        try:
            limit_val = int(expr.this)
        except ValueError as exc:
            raise SQLGuardError(f"Invalid LIMIT literal: {expr.this!r}") from exc
        if limit_val < 0 or limit_val > max_limit:
            raise SQLGuardError(f"LIMIT {limit_val} exceeds allowed range 0..{max_limit}.")


def validate_and_normalize_sql(
    raw_sql: str,
    default_limit: int = DEFAULT_LIMIT,
    max_limit: int = MAX_LIMIT,
) -> str:
    """Parse SQL into a Postgres AST, enforce read-only SELECT/UNION rules, and cap rows."""
    if not raw_sql or not raw_sql.strip():
        raise SQLGuardError("Empty SQL input is forbidden.")
    try:
        statements = sqlglot.parse(raw_sql, read="postgres")
    except ParseError as exc:
        raise SQLGuardError(f"SQL parse error: {exc}") from exc

    if len(statements) != 1 or statements[0] is None:
        raise SQLGuardError(f"Expected exactly 1 SQL statement, got {len(statements)}.")

    stmt = statements[0]
    if not isinstance(stmt, (exp.Select, exp.Union)):
        raise SQLGuardError(f"Only SELECT or UNION queries are allowed, got {type(stmt).__name__}.")

    for forbidden in stmt.find_all(FORBIDDEN_NODES):
        raise SQLGuardError(f"Forbidden SQL AST node detected: {type(forbidden).__name__}.")

    for func_node in stmt.find_all((exp.Func, exp.Anonymous)):
        names = {(func_node.name or "").lower(), (func_node.sql_name() or "").lower()}
        blocked = names & FORBIDDEN_FUNCTIONS
        if blocked:
            raise SQLGuardError(f"Forbidden PostgreSQL function: {min(blocked)}.")

    _validate_limits(stmt, max_limit=max_limit)
    if stmt.args.get("limit") is None:
        stmt = stmt.limit(default_limit)

    return stmt.sql(dialect="postgres")
