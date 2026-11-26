"""Inference wrapper supporting offline mock mode and QLoRA PEFT adapter inference."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Protocol

import yaml

_TABLE_RE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([\"`\[]?\w+[\"`\]]?)", re.IGNORECASE)
_HF_REPO_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")
_LOCAL_ONLY_PREFIXES = ("outputs/", "checkpoints/", "models/", "./", "../")

REPAIR_SYSTEM_PROMPT = (
    "You are a PostgreSQL SQL expert fixing a failed SQL query. Verify table alias declaration order "
    "(FROM/JOIN order) and exact column ownership against the schema, then return only a single valid "
    "PostgreSQL SELECT statement that fixes the error with no markdown backticks or explanation.\n\n"
    "PostgreSQL rules:\n"
    "1. Use ONLY tables and columns explicitly defined in the provided schema.\n"
    "2. Follow declared FOREIGN KEY relationships for all JOINs; never invent joins between unrelated IDs.\n"
    "3. Enforce strict PostgreSQL GROUP BY: every non-aggregated expression in SELECT must appear in GROUP BY.\n"
    "4. Compute date/timestamp differences in days with EXTRACT(EPOCH FROM (end_ts - start_ts)) / 86400.0 (never julianday).\n"
    "5. When combining multiple one-to-many tables in aggregations (e.g., order_items and reviews), pre-aggregate in CTEs (WITH ...)."
)


class PredictorProtocol(Protocol):
    mode: str

    def generate(self, question: str, schema_ddl: str) -> str:
        """Generate a candidate SQL query for a question and schema DDL."""

    def repair(self, question: str, schema_ddl: str, failed_sql: str, error_message: str) -> str:
        """Repair a failed SQL query using the PostgreSQL execution error message."""


def _resolve_target_table(question: str, schema_ddl: str) -> str:
    tables = [m.strip('"`[]') for m in _TABLE_RE.findall(schema_ddl)]
    q_lower = question.lower()
    return next((t for t in tables if t.lower() in q_lower), tables[0] if tables else "items")


class MockPredictor:
    """Deterministic rule-based predictor for offline API tests and CI."""

    mode = "mock"

    def generate(self, question: str, schema_ddl: str) -> str:
        table = _resolve_target_table(question, schema_ddl)
        q_lower = question.lower()
        if "pg_sleep" in q_lower:
            return "SELECT pg_sleep(10)"
        if "truncate" in q_lower:
            return f"TRUNCATE TABLE {table}"
        if "delete" in q_lower:
            return f"DELETE FROM {table}"
        if "drop" in q_lower:
            return f"DROP TABLE {table}"
        if "count" in q_lower or "how many" in q_lower:
            return f"SELECT COUNT(*) AS total_count FROM {table}"
        return f"SELECT * FROM {table}"

    def repair(self, question: str, schema_ddl: str, failed_sql: str, error_message: str) -> str:
        del error_message
        table = _resolve_target_table(question, schema_ddl)
        if "count" in failed_sql.lower() or "count" in question.lower() or "how many" in question.lower():
            return f"SELECT COUNT(*) AS total_count FROM {table}"
        return f"SELECT * FROM {table}"


def _is_hf_repo_id(value: str) -> bool:
    return (
        bool(_HF_REPO_ID_RE.match(value))
        and ".." not in value
        and not value.startswith(_LOCAL_ONLY_PREFIXES)
    )


def _resolve_adapter_location(raw_adapter: str | Path) -> str | Path:
    if isinstance(raw_adapter, Path):
        if raw_adapter.is_dir():
            return raw_adapter
        posix_str = raw_adapter.as_posix()
        if _is_hf_repo_id(posix_str):
            return posix_str
        raise FileNotFoundError(f"QLoRA adapter directory not found: {raw_adapter}")

    candidate = raw_adapter.strip()
    local_path = Path(candidate)
    if local_path.is_dir():
        return local_path
    if _is_hf_repo_id(candidate):
        return candidate
    raise FileNotFoundError(f"QLoRA adapter directory or Hugging Face repo ID not found: {candidate}")


class QLoRAPredictor:
    """Loads Qwen2.5-3B-Instruct + saved QLoRA adapter for deterministic SQL generation."""

    mode = "qlora"

    def __init__(self, config_path: Path, adapter_dir: str | Path | None = None) -> None:
        from eval.evaluate import load_hf_model_and_tokenizer

        cfg: dict[str, Any] = dict(yaml.safe_load(config_path.read_text(encoding="utf-8")))
        raw_ref: str | Path = adapter_dir if adapter_dir is not None else str(cfg["training"]["output_dir"])
        eff_adapter = _resolve_adapter_location(raw_ref)
        self._model, self._tokenizer = load_hf_model_and_tokenizer(cfg, eff_adapter)

    def _infer_cleaned_sql(self, system_prompt: str, user_content: str) -> str:
        from eval.evaluate import generate_sql_greedy
        from eval.sqlite_exec import strip_markdown_sql

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        raw_sql, _ = generate_sql_greedy(self._model, self._tokenizer, messages)
        cleaned_sql, _ = strip_markdown_sql(raw_sql)
        return cleaned_sql

    def generate(self, question: str, schema_ddl: str) -> str:
        from training.prepare_dataset import SYSTEM_PROMPT

        return self._infer_cleaned_sql(
            SYSTEM_PROMPT,
            f"Schema:\n{schema_ddl}\n\nQuestion:\n{question.strip()}",
        )

    def repair(self, question: str, schema_ddl: str, failed_sql: str, error_message: str) -> str:
        user_content = (
            f"Schema:\n{schema_ddl}\n\n"
            f"Question:\n{question.strip()}\n\n"
            f"Failed SQL:\n{failed_sql.strip()}\n\n"
            f"PostgreSQL Error:\n{error_message.strip()}\n\n"
            "Verify alias declaration order (FROM/JOIN) and column ownership, then return only a single valid PostgreSQL SELECT statement:"
        )
        return self._infer_cleaned_sql(REPAIR_SYSTEM_PROMPT, user_content)


def create_predictor(
    mode: str | None = None,
    config_path: Path | None = None,
    adapter_dir: str | Path | None = None,
) -> PredictorProtocol:
    """Instantiate predictor according to INFERENCE_MODE (`mock` or `qlora`)."""
    resolved_mode = (mode or os.getenv("INFERENCE_MODE", "mock")).strip().lower()
    if resolved_mode == "mock":
        return MockPredictor()
    if resolved_mode == "qlora":
        cfg_path = config_path or Path(os.getenv("CONFIG_PATH", "training/config.yaml"))
        raw_adapter = os.getenv("ADAPTER_DIR")
        cleaned_env = raw_adapter.strip() if raw_adapter else ""
        eff_adapter: str | Path | None = adapter_dir if adapter_dir is not None else (cleaned_env or None)
        return QLoRAPredictor(cfg_path, eff_adapter)
    raise ValueError(f"Unsupported INFERENCE_MODE={resolved_mode!r}; expected 'mock' or 'qlora'.")
