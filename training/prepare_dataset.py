"""Schema-disjoint Spider dataset loader and TRL prompt/completion formatter."""

from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import tempfile
from collections import defaultdict
from collections.abc import Mapping, Sequence
from contextlib import closing
from pathlib import Path
from typing import Any, TypedDict

import yaml

SYSTEM_PROMPT = (
    "You are a SQLite SQL expert. Given a database schema and a question, "
    "return only a single valid SQL query with no markdown backticks or explanation."
)
_FENCE_RE = re.compile(r"^```(?:sql)?\s*|\s*```$", re.IGNORECASE)


class SpiderRecord(TypedDict):
    db_id: str
    question: str
    query: str


class PreparedExample(TypedDict):
    db_id: str
    prompt: list[dict[str, str]]
    completion: list[dict[str, str]]


def clean_sql(raw_sql: str) -> str:
    """Strip markdown fences/backticks and normalize newlines into raw SQL."""
    stripped = _FENCE_RE.sub("", raw_sql.strip()).strip().replace("`", "")
    return re.sub(r"\s*\n\s*", " ", stripped).strip()


def resolve_sqlite_path(db_dir: Path, db_id: str) -> Path:
    """Resolve `<db_dir>/<db_id>/<db_id>.sqlite` or flat `<db_id>.sqlite`."""
    for candidate in (db_dir / db_id / f"{db_id}.sqlite", db_dir / f"{db_id}.sqlite"):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"SQLite file not found for db_id={db_id!r} in {db_dir}")


def extract_sqlite_ddl(db_path: Path) -> str:
    """Extract compact CREATE TABLE DDL statements directly from sqlite_master."""
    if not db_path.is_file():
        raise FileNotFoundError(f"SQLite database does not exist: {db_path}")
    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    sql_q = "SELECT sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL ORDER BY rowid"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        rows = conn.execute(sql_q).fetchall()
    ddls = [
        f"{compact};"
        for (raw,) in rows
        if (compact := re.sub(r"\s+", " ", " ".join(ln.strip() for ln in str(raw).splitlines() if ln.strip() and not ln.strip().startswith("--"))).strip().rstrip(";"))
    ]
    if not ddls:
        raise ValueError(f"No user tables found in {db_path}")
    return "\n".join(ddls)


def assert_disjoint_db_ids(train_rows: Sequence[Mapping[str, Any]], val_rows: Sequence[Mapping[str, Any]]) -> None:
    """Verify both splits are non-empty and share zero db_id values."""
    train_dbs, val_dbs = {str(r["db_id"]) for r in train_rows}, {str(r["db_id"]) for r in val_rows}
    assert train_dbs and val_dbs, "Both train and validation splits must be non-empty."
    overlap = train_dbs & val_dbs
    assert not overlap, f"Database leakage across splits: {sorted(overlap)}"


def split_by_db_id(
    records: Sequence[SpiderRecord], val_ratio: float = 0.15, seed: int = 42
) -> tuple[list[SpiderRecord], list[SpiderRecord]]:
    """Split records strictly by db_id so schemas never leak between train and val."""
    if not 0.0 < val_ratio < 1.0:
        raise ValueError(f"val_ratio must be in (0, 1), got {val_ratio}")
    grouped: dict[str, list[SpiderRecord]] = defaultdict(list)
    for rec in records:
        grouped[rec["db_id"]].append(rec)
    db_ids = sorted(grouped)
    if len(db_ids) < 2:
        raise ValueError("Need at least 2 distinct db_ids for a disjoint split.")
    random.Random(seed).shuffle(db_ids)
    val_count = min(max(1, round(len(db_ids) * val_ratio)), len(db_ids) - 1)
    train_recs = [rec for db in db_ids[val_count:] for rec in grouped[db]]
    val_recs = [rec for db in db_ids[:val_count] for rec in grouped[db]]
    assert_disjoint_db_ids(train_recs, val_recs)
    return train_recs, val_recs


def format_example(db_id: str, schema_ddl: str, question: str, raw_sql: str) -> PreparedExample:
    """Format one NL-to-SQL pair for TRL SFTConfig(completion_only_loss=True)."""
    return {
        "db_id": db_id,
        "prompt": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": f"Schema:\n{schema_ddl}\n\nQuestion:\n{question.strip()}"}],
        "completion": [{"role": "assistant", "content": clean_sql(raw_sql)}],
    }


def format_split(records: Sequence[SpiderRecord], db_dir: Path, ddl_cache: dict[str, str]) -> list[PreparedExample]:
    """Attach cached SQLite DDL schemas and format records into prompt/completion rows."""
    out: list[PreparedExample] = []
    for rec in records:
        db_id = rec["db_id"]
        ddl = ddl_cache.setdefault(db_id, extract_sqlite_ddl(resolve_sqlite_path(db_dir, db_id))) if db_id not in ddl_cache else ddl_cache[db_id]
        out.append(format_example(db_id, ddl, rec["question"], rec["query"]))
    return out


def load_spider_records(hf_dataset_id: str) -> tuple[list[SpiderRecord], list[SpiderRecord]]:
    """Load Spider train and validation splits from Hugging Face datasets."""
    from datasets import load_dataset

    def _to_rec(row: Mapping[str, Any]) -> SpiderRecord:
        return SpiderRecord(db_id=str(row["db_id"]), question=str(row["question"]), query=str(row["query"]))

    ds = load_dataset(hf_dataset_id)
    return [_to_rec(r) for r in ds["train"]], [_to_rec(r) for r in ds["validation"]]


def generate_smoketest_data(root_dir: Path) -> tuple[list[SpiderRecord], Path]:
    """Create 3 tiny SQLite databases and 50 valid NL-to-SQL examples offline."""
    db_dir = root_dir / "databases"
    specs: list[tuple[str, str, str, str, list[Any], list[tuple[str, str]]]] = [
        ("school_db", "CREATE TABLE departments (id INTEGER PRIMARY KEY, name TEXT NOT NULL); CREATE TABLE students (id INTEGER PRIMARY KEY, name TEXT NOT NULL, dept_id INTEGER REFERENCES departments(id), gpa REAL); INSERT INTO departments VALUES (1, 'CS'), (2, 'Math'); INSERT INTO students VALUES (1, 'Alice', 1, 3.9), (2, 'Bob', 2, 3.4);",
         "Students with GPA >= {}?", "SELECT name FROM students WHERE gpa >= {}", [2.5, 2.7, 2.9, 3.0, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9],
         [("Count all students.", "SELECT COUNT(*) FROM students"), ("Average student GPA.", "SELECT AVG(gpa) FROM students"), ("List department names.", "SELECT name FROM departments ORDER BY name"), ("Students with departments.", "SELECT s.name, d.name FROM students s JOIN departments d ON s.dept_id = d.id")]),
        ("store_db", "CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL, city TEXT NOT NULL); CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id), amount REAL, status TEXT); INSERT INTO customers VALUES (1, 'Cara', 'NYC'), (2, 'Dan', 'Austin'); INSERT INTO orders VALUES (1, 1, 120.0, 'paid'), (2, 2, 45.0, 'open');",
         "Orders over {}?", "SELECT id, amount FROM orders WHERE amount > {}", [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 115, 125],
         [("Count orders.", "SELECT COUNT(*) FROM orders"), ("Sum paid orders.", "SELECT SUM(amount) FROM orders WHERE status = 'paid'"), ("List cities.", "SELECT DISTINCT city FROM customers"), ("Orders with customers.", "SELECT c.name, o.amount FROM customers c JOIN orders o ON c.id = o.customer_id")]),
        ("clinic_db", "CREATE TABLE doctors (id INTEGER PRIMARY KEY, name TEXT NOT NULL, specialty TEXT NOT NULL); CREATE TABLE visits (id INTEGER PRIMARY KEY, doctor_id INTEGER REFERENCES doctors(id), patient_name TEXT, fee REAL); INSERT INTO doctors VALUES (1, 'Dr. Lee', 'Cardiology'), (2, 'Dr. Patel', 'Pediatrics'); INSERT INTO visits VALUES (1, 1, 'Sam', 150.0), (2, 2, 'Mia', 90.0);",
         "Visits with fee >= {}?", "SELECT patient_name FROM visits WHERE fee >= {}", [50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150, 160],
         [("Count doctors.", "SELECT COUNT(*) FROM doctors"), ("Total fees.", "SELECT SUM(fee) FROM visits"), ("List specialties.", "SELECT DISTINCT specialty FROM doctors"), ("Visits with doctors.", "SELECT d.name, v.patient_name FROM doctors d JOIN visits v ON d.id = v.doctor_id")]),
    ]
    records: list[SpiderRecord] = []
    for db_id, script, q_tmpl, sql_tmpl, vals, extras in specs:
        sqlite_path = db_dir / db_id / f"{db_id}.sqlite"
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(sqlite_path)) as conn:
            conn.executescript(script)
        records.extend(SpiderRecord(db_id=db_id, question=q_tmpl.format(v), query=sql_tmpl.format(v)) for v in vals)
        records.extend(SpiderRecord(db_id=db_id, question=q, query=sql) for q, sql in extras)
    return records, db_dir


def write_jsonl(rows: Sequence[Mapping[str, Any]], path: Path) -> None:
    """Write prepared examples to a UTF-8 JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare schema-disjoint Spider NL-to-SQL JSONL splits.")
    parser.add_argument("--config", type=Path, default=Path("training/config.yaml"))
    parser.add_argument("--smoketest", action="store_true", help="Generate offline 3-DB / 50-row smoketest JSONL.")
    parser.add_argument("--db-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--val-ratio", type=float, default=None)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args(list(argv) if argv is not None else None)
    cfg: dict[str, Any] = yaml.safe_load(args.config.read_text(encoding="utf-8"))["dataset"]
    seed, val_ratio = int(args.seed if args.seed is not None else cfg["seed"]), float(args.val_ratio if args.val_ratio is not None else cfg["val_ratio"])
    out_dir = args.output_dir or Path(cfg["smoketest_output_dir"] if args.smoketest else cfg["output_dir"])
    ddl_cache: dict[str, str] = {}
    if args.smoketest:
        with tempfile.TemporaryDirectory(prefix="spider_smoketest_") as tmp_dir:
            all_records, db_dir = generate_smoketest_data(Path(tmp_dir))
            train_raw, val_raw = split_by_db_id(all_records, val_ratio=val_ratio, seed=seed)
            train_rows, val_rows = format_split(train_raw, db_dir, ddl_cache), format_split(val_raw, db_dir, ddl_cache)
    else:
        db_dir = args.db_dir or Path(cfg["spider_db_dir"])
        train_raw, val_raw = load_spider_records(str(cfg["hf_dataset_id"]))
        assert_disjoint_db_ids(train_raw, val_raw)
        train_rows, val_rows = format_split(train_raw, db_dir, ddl_cache), format_split(val_raw, db_dir, ddl_cache)
    assert_disjoint_db_ids(train_rows, val_rows)
    train_path, val_path = out_dir / str(cfg["train_filename"]), out_dir / str(cfg["val_filename"])
    write_jsonl(train_rows, train_path)
    write_jsonl(val_rows, val_path)
    print(json.dumps({"mode": "smoketest" if args.smoketest else "spider", "train_rows": len(train_rows), "val_rows": len(val_rows), "total_rows": len(train_rows) + len(val_rows), "train_db_ids": sorted({r["db_id"] for r in train_rows}), "val_db_ids": sorted({r["db_id"] for r in val_rows}), "train_path": str(train_path), "val_path": str(val_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
