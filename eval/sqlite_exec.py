"""Read-only SQLite executor with monotonic timeout and multiset comparison."""

from __future__ import annotations

import re
import sqlite3
import time
from collections import Counter
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sqlglot
from sqlglot.errors import SqlglotError

_FENCE_BODY_RE = re.compile(r"```(?:sql)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class ExecResult:
    success: bool
    rows: list[tuple[Any, ...]]
    error: str | None
    timed_out: bool


@dataclass(frozen=True)
class EvalComparison:
    raw_valid: bool
    cleaned_valid: bool
    exact_match: bool
    cleaned_sql: str
    had_markdown_fence: bool
    pred_error: str | None
    timed_out: bool


def strip_markdown_sql(raw_sql: str) -> tuple[str, bool]:
    """Post-process predicted text by removing accidental markdown SQL fences."""
    text = raw_sql.strip()
    match = _FENCE_BODY_RE.search(text)
    if match:
        return match.group(1).strip(), True
    if text.startswith("`") and text.endswith("`") and len(text) >= 2:
        return text.strip("`").strip(), True
    return text, False


def has_top_level_order_by(sql: str) -> bool:
    """Return True if the outer query has an ORDER BY clause."""
    try:
        parsed = sqlglot.parse_one(sql, read="sqlite")
        return parsed.args.get("order") is not None
    except SqlglotError:
        return bool(re.search(r"\border\s+by\b", sql, re.IGNORECASE))


def execute_readonly_sql(db_path: Path, sql: str, timeout_sec: float = 3.0) -> ExecResult:
    """Execute SQL read-only against SQLite with a progress-handler wall-clock timeout."""
    if not db_path.is_file():
        raise FileNotFoundError(f"SQLite database not found: {db_path}")
    if not sql.strip():
        return ExecResult(False, [], "Empty SQL query", False)

    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    deadline = time.monotonic() + timeout_sec
    timed_out = False

    def _check_deadline() -> int:
        nonlocal timed_out
        if time.monotonic() > deadline:
            timed_out = True
            return 1
        return 0

    with closing(sqlite3.connect(uri, uri=True)) as conn:
        conn.execute("PRAGMA query_only = ON")
        conn.set_progress_handler(_check_deadline, 5000)
        try:
            rows = [tuple(row) for row in conn.execute(sql).fetchall()]
            return ExecResult(True, rows, None, False)
        except sqlite3.Error as exc:
            msg = f"Query exceeded {timeout_sec:.2f}s timeout" if timed_out else str(exc)
            return ExecResult(False, [], msg, timed_out)
        finally:
            conn.set_progress_handler(None, 0)


def results_match(
    pred_rows: Sequence[tuple[Any, ...]],
    gold_rows: Sequence[tuple[Any, ...]],
    ordered: bool,
) -> bool:
    """Compare query results as ordered lists (ORDER BY) or duplicate-preserving multisets."""
    if ordered:
        return list(pred_rows) == list(gold_rows)
    return Counter(pred_rows) == Counter(gold_rows)


def evaluate_prediction(
    db_path: Path,
    raw_pred_sql: str,
    gold_sql: str,
    timeout_sec: float = 3.0,
) -> EvalComparison:
    """Evaluate raw and fence-cleaned prediction SQL against gold SQLite output."""
    raw_res = execute_readonly_sql(db_path, raw_pred_sql, timeout_sec=timeout_sec)
    cleaned_sql, had_fence = strip_markdown_sql(raw_pred_sql)
    clean_res = (
        execute_readonly_sql(db_path, cleaned_sql, timeout_sec=timeout_sec)
        if (had_fence or cleaned_sql != raw_pred_sql)
        else raw_res
    )
    gold_res = execute_readonly_sql(db_path, gold_sql, timeout_sec=timeout_sec)
    ordered = has_top_level_order_by(gold_sql)
    exact = bool(clean_res.success and gold_res.success and results_match(clean_res.rows, gold_res.rows, ordered))
    return EvalComparison(
        raw_valid=raw_res.success,
        cleaned_valid=clean_res.success,
        exact_match=exact,
        cleaned_sql=cleaned_sql,
        had_markdown_fence=had_fence,
        pred_error=clean_res.error,
        timed_out=clean_res.timed_out,
    )
