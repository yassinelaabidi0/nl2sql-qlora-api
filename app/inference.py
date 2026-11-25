"""Inference wrapper supporting offline mock mode and QLoRA PEFT adapter inference."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Protocol

import yaml

_TABLE_RE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([\"`\[]?\w+[\"`\]]?)", re.IGNORECASE)


class PredictorProtocol(Protocol):
    mode: str

    def generate(self, question: str, schema_ddl: str) -> str:
        """Generate a candidate SQL query for a question and schema DDL."""


class MockPredictor:
    """Deterministic rule-based predictor for offline API tests and CI."""

    mode = "mock"

    def generate(self, question: str, schema_ddl: str) -> str:
        match = _TABLE_RE.search(schema_ddl)
        table = match.group(1).strip('"`[]') if match else "items"
        q_lower = question.lower()
        if "count" in q_lower or "how many" in q_lower:
            return f"SELECT COUNT(*) AS total_count FROM {table}"
        return f"SELECT * FROM {table}"


class QLoRAPredictor:
    """Loads Qwen2.5-3B-Instruct + saved QLoRA adapter for deterministic SQL generation."""

    mode = "qlora"

    def __init__(self, config_path: Path, adapter_dir: Path | None = None) -> None:
        from eval.evaluate import load_hf_model_and_tokenizer

        cfg: dict[str, Any] = dict(yaml.safe_load(config_path.read_text(encoding="utf-8")))
        eff_adapter = adapter_dir or Path(cfg["training"]["output_dir"])
        if not eff_adapter.is_dir():
            raise FileNotFoundError(f"QLoRA adapter directory not found: {eff_adapter}")
        self._model, self._tokenizer = load_hf_model_and_tokenizer(cfg, eff_adapter)

    def generate(self, question: str, schema_ddl: str) -> str:
        from eval.evaluate import generate_sql_greedy
        from eval.sqlite_exec import strip_markdown_sql
        from training.prepare_dataset import SYSTEM_PROMPT

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Schema:\n{schema_ddl}\n\nQuestion:\n{question.strip()}"},
        ]
        raw_sql, _ = generate_sql_greedy(self._model, self._tokenizer, messages)
        cleaned_sql, _ = strip_markdown_sql(raw_sql)
        return cleaned_sql


def create_predictor(
    mode: str | None = None,
    config_path: Path | None = None,
    adapter_dir: Path | None = None,
) -> PredictorProtocol:
    """Instantiate predictor according to INFERENCE_MODE (`mock` or `qlora`)."""
    resolved_mode = (mode or os.getenv("INFERENCE_MODE", "mock")).strip().lower()
    if resolved_mode == "mock":
        return MockPredictor()
    if resolved_mode == "qlora":
        cfg_path = config_path or Path(os.getenv("CONFIG_PATH", "training/config.yaml"))
        raw_adapter = os.getenv("ADAPTER_DIR")
        eff_adapter = adapter_dir or (Path(raw_adapter) if raw_adapter else None)
        return QLoRAPredictor(cfg_path, eff_adapter)
    raise ValueError(f"Unsupported INFERENCE_MODE={resolved_mode!r}; expected 'mock' or 'qlora'.")
