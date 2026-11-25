"""Tests for schema-disjoint Spider dataset preparation."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from training.prepare_dataset import (
    SpiderRecord,
    assert_disjoint_db_ids,
    clean_sql,
    extract_sqlite_ddl,
    format_example,
    generate_smoketest_data,
    main,
    split_by_db_id,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_extract_sqlite_ddl_reads_sqlite_master(tmp_path: Path) -> None:
    db_path = tmp_path / "org.sqlite"
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            """
                -- Department lookup table
                CREATE TABLE departments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL
                )
                """
        )
        conn.execute(
            """
                CREATE TABLE employees (
                    id INTEGER PRIMARY KEY,
                    dept_id INTEGER REFERENCES departments(id),
                    salary REAL
                )
                """
        )
    ddl = extract_sqlite_ddl(db_path)
    assert "CREATE TABLE departments" in ddl
    assert "CREATE TABLE employees" in ddl
    assert "REFERENCES departments(id)" in ddl
    assert "sqlite_sequence" not in ddl
    assert "-- Department lookup table" not in ddl


def test_split_by_db_id_enforces_zero_overlap() -> None:
    records = [
        SpiderRecord(db_id=f"db_{i}", question=f"Q{i}_{j}", query=f"SELECT {j}")
        for i in range(5)
        for j in range(4)
    ]
    train_a, val_a = split_by_db_id(records, val_ratio=0.4, seed=42)
    train_b, val_b = split_by_db_id(records, val_ratio=0.4, seed=42)
    assert train_a == train_b and val_a == val_b
    assert len(train_a) + len(val_a) == len(records)
    train_dbs = {r["db_id"] for r in train_a}
    val_dbs = {r["db_id"] for r in val_a}
    assert train_dbs and val_dbs
    assert train_dbs.isdisjoint(val_dbs)


def test_assert_disjoint_db_ids_rejects_leakage() -> None:
    train = [{"db_id": "school_db"}, {"db_id": "store_db"}]
    val = [{"db_id": "store_db"}, {"db_id": "clinic_db"}]
    with pytest.raises(AssertionError, match="leakage"):
        assert_disjoint_db_ids(train, val)


def test_clean_sql_and_prompt_completion_format() -> None:
    raw = "```sql\nSELECT `name`\nFROM students\nWHERE gpa >= 3.5;\n```"
    cleaned = clean_sql(raw)
    assert "`" not in cleaned
    assert cleaned == "SELECT name FROM students WHERE gpa >= 3.5;"

    example = format_example("school_db", "CREATE TABLE students (name TEXT, gpa REAL);", "Top students?", raw)
    assert example["db_id"] == "school_db"
    assert example["prompt"][0]["role"] == "system"
    assert example["prompt"][1]["role"] == "user"
    assert "CREATE TABLE students" in example["prompt"][1]["content"]
    assert "Top students?" in example["prompt"][1]["content"]
    assert example["completion"] == [{"role": "assistant", "content": cleaned}]


def test_smoketest_queries_execute_and_cli_outputs_50_rows(tmp_path: Path) -> None:
    records, db_dir = generate_smoketest_data(tmp_path / "raw")
    assert len(records) == 50
    for rec in records:
        sqlite_path = db_dir / rec["db_id"] / f"{rec['db_id']}.sqlite"
        with closing(sqlite3.connect(sqlite_path)) as conn:
            conn.execute(rec["query"]).fetchall()

    out_dir = tmp_path / "smoketest_out"
    exit_code = main(
        ["--config", str(REPO_ROOT / "training" / "config.yaml"), "--smoketest", "--output-dir", str(out_dir)]
    )
    assert exit_code == 0

    train_rows = _read_jsonl(out_dir / "train.jsonl")
    val_rows = _read_jsonl(out_dir / "val.jsonl")
    assert len(train_rows) + len(val_rows) == 50
    assert_disjoint_db_ids(train_rows, val_rows)

    for row in train_rows + val_rows:
        user_msg = row["prompt"][1]["content"]
        sql_out = row["completion"][0]["content"]
        assert "CREATE TABLE" in user_msg
        assert sql_out and "`" not in sql_out


def test_smoketest_module_entrypoint(tmp_path: Path) -> None:
    out_dir = tmp_path / "cli_out"
    proc = subprocess.run(
        [sys.executable, "-m", "training.prepare_dataset", "--smoketest", "--output-dir", str(out_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    summary = json.loads(proc.stdout)
    assert summary["total_rows"] == 50
    assert set(summary["train_db_ids"]).isdisjoint(summary["val_db_ids"])


def test_prepare_dataset_line_budget() -> None:
    line_count = len((REPO_ROOT / "training" / "prepare_dataset.py").read_text(encoding="utf-8").splitlines())
    assert line_count < 200, f"prepare_dataset.py exceeded 200-line limit: {line_count} lines"
