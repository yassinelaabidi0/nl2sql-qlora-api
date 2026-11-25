"""Tests for read-only SQLite execution, timeout/multiset logic, and 3-way evaluation."""

from __future__ import annotations

import inspect
import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

from eval.evaluate import main, select_few_shot_examples
from eval.sqlite_exec import (
    evaluate_prediction,
    execute_readonly_sql,
    has_top_level_order_by,
    results_match,
    strip_markdown_sql,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _make_sample_db(db_path: Path) -> Path:
    with closing(sqlite3.connect(db_path)) as conn:
        conn.executescript(
            """
            CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT, score INTEGER);
            INSERT INTO items VALUES (1, 'a', 10), (2, 'b', 10), (3, 'c', 20);
            """
        )
    return db_path


def test_readonly_blocks_mutations(tmp_path: Path) -> None:
    db_path = _make_sample_db(tmp_path / "test.sqlite")
    for bad_sql in ("DROP TABLE items", "INSERT INTO items VALUES (4, 'd', 30)", "DELETE FROM items"):
        res = execute_readonly_sql(db_path, bad_sql)
        assert res.success is False
        assert res.error is not None

    check = execute_readonly_sql(db_path, "SELECT COUNT(*) FROM items")
    assert check.success is True
    assert check.rows == [(3,)]


def test_progress_handler_enforces_timeout(tmp_path: Path) -> None:
    sig = inspect.signature(execute_readonly_sql)
    assert sig.parameters["timeout_sec"].default == 3.0

    db_path = _make_sample_db(tmp_path / "slow.sqlite")
    slow_cte = (
        "WITH RECURSIVE cnt(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM cnt) "
        "SELECT COUNT(*) FROM cnt"
    )
    res = execute_readonly_sql(db_path, slow_cte, timeout_sec=0.15)
    assert res.success is False
    assert res.timed_out is True
    assert res.error is not None and "timeout" in res.error.lower()


def test_multiset_and_order_by_comparison() -> None:
    assert results_match([(1, "a"), (2, "b")], [(2, "b"), (1, "a")], ordered=False) is True
    assert results_match([(10,), (10,)], [(10,)], ordered=False) is False
    assert results_match([(1,), (2,)], [(2,), (1,)], ordered=True) is False
    assert results_match([(1,), (2,)], [(1,), (2,)], ordered=True) is True

    assert has_top_level_order_by("SELECT name FROM items ORDER BY score DESC") is True
    assert has_top_level_order_by("SELECT name FROM (SELECT name FROM items ORDER BY score) sub") is False
    assert has_top_level_order_by("SELECT name FROM items WHERE name = 'order by'") is False


def test_strip_markdown_sql_and_raw_vs_cleaned_validity(tmp_path: Path) -> None:
    db_path = _make_sample_db(tmp_path / "fence.sqlite")
    fenced = "```sql\nSELECT name FROM items WHERE score = 20;\n```"
    cleaned, had_fence = strip_markdown_sql(fenced)
    assert had_fence is True
    assert cleaned == "SELECT name FROM items WHERE score = 20;"

    cmp = evaluate_prediction(db_path, fenced, "SELECT name FROM items WHERE score = 20")
    assert cmp.raw_valid is False
    assert cmp.cleaned_valid is True
    assert cmp.had_markdown_fence is True
    assert cmp.exact_match is True


def test_select_few_shot_examples_disjoint() -> None:
    train = [
        {"db_id": "db_a", "prompt": [{}, {}], "completion": [{}]},
        {"db_id": "db_a", "prompt": [{}, {}], "completion": [{}]},
        {"db_id": "db_b", "prompt": [{}, {}], "completion": [{}]},
    ]
    val = [{"db_id": "db_c", "prompt": [{}, {}], "completion": [{}]}]
    shots = select_few_shot_examples(train, val, k=3)
    assert len(shots) == 3
    assert {s["db_id"] for s in shots} == {"db_a", "db_b"}


def test_evaluate_smoketest_mock_inference_end_to_end(tmp_path: Path) -> None:
    out_dir = tmp_path / "results"
    rc = main(["--smoketest", "--mock-inference", "--output-dir", str(out_dir)])
    assert rc == 0

    json_path = out_dir / "benchmark_summary.json"
    md_path = out_dir / "benchmark_summary.md"
    assert json_path.is_file() and md_path.is_file()

    report = json.loads(json_path.read_text(encoding="utf-8"))
    assert report["mode"] == "smoketest"
    assert report["mock_inference"] is True
    assert report["num_examples"] > 0

    modes = {row["mode"]: row for row in report["results"]}
    assert set(modes) == {"base_zero_shot", "base_3_shot", "qlora_finetuned"}
    assert modes["base_zero_shot"]["fenced_outputs"] > 0
    assert modes["base_zero_shot"]["raw_valid_sql_rate_pct"] < modes["base_zero_shot"]["valid_sql_rate_pct"]
    assert modes["qlora_finetuned"]["execution_accuracy_pct"] == 100.0
    for row in report["results"]:
        assert 0.0 <= row["execution_accuracy_pct"] <= row["valid_sql_rate_pct"] <= 100.0
        assert row["latency_p50_ms"] <= row["latency_p95_ms"]
        assert row["peak_vram_mb"] == 0.0

    md_text = md_path.read_text(encoding="utf-8")
    assert "base_zero_shot" in md_text and "base_3_shot" in md_text and "qlora_finetuned" in md_text


def test_evaluate_module_entrypoint(tmp_path: Path) -> None:
    out_dir = tmp_path / "cli_results"
    proc = subprocess.run(
        [sys.executable, "-m", "eval.evaluate", "--smoketest", "--mock-inference", "--output-dir", str(out_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    summary = json.loads(proc.stdout)
    assert len(summary["results"]) == 3


def test_phase2_line_budgets() -> None:
    exec_lines = len((REPO_ROOT / "eval" / "sqlite_exec.py").read_text(encoding="utf-8").splitlines())
    eval_lines = len((REPO_ROOT / "eval" / "evaluate.py").read_text(encoding="utf-8").splitlines())
    assert exec_lines < 150, f"sqlite_exec.py exceeded 150-line limit: {exec_lines} lines"
    assert eval_lines < 200, f"evaluate.py exceeded 200-line limit: {eval_lines} lines"
