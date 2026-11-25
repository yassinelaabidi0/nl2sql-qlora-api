# Local NL-to-SQL LLM (QLoRA) & Hardened FastAPI Microservice

Production-grade Natural-Language-to-SQL system fine-tuning `Qwen/Qwen2.5-3B-Instruct` via 4-bit NF4 QLoRA on schema-disjoint Spider splits, evaluated with read-only SQLite execution accuracy, and served behind an AST-validated FastAPI + PostgreSQL microservice.

## Architecture

```mermaid
flowchart LR
    Q["User Question"] --> API["FastAPI POST /query (asyncio.to_thread)"]
    API --> LLM["Qwen2.5-3B QLoRA / Mock Predictor"]
    LLM --> Guard["app/guard.py (SQLGlot Postgres AST + LIMIT 100)"]
    Guard -->|Rejected| Audit["nl2sql_logger: INSERT query_logs (rejected)"]
    Guard -->|Approved| RO["nl2sql_ro: Read-Only SELECT (3s timeout)"]
    RO --> AuditOK["nl2sql_logger: INSERT query_logs (success)"]
    RO --> Resp["JSON QueryResponse"]
```

### Design & Security Guardrails
- **Schema-Disjoint Splits:** `training/prepare_dataset.py` extracts compact `CREATE TABLE` DDL from `sqlite_master` and enforces zero `db_id` overlap across train/validation splits.
- **Completion-Only Loss:** `training/train_qlora.py` uses TRL `SFTConfig(completion_only_loss=True)` with `prompt`/`completion` formatting so prompt/DDL tokens are masked (`-100`) during QLoRA training.
- **Read-Only Evaluation:** `eval/sqlite_exec.py` runs SQLite `?mode=ro` with a `set_progress_handler` 3.0s monotonic timeout and duplicate-preserving multiset (or `ORDER BY` list) comparison.
- **Defense-in-Depth SQL Serving:** `app/guard.py` validates the full Postgres AST via `sqlglot` (single `Select`/`Union`, blocks writable CTEs, DML/DDL, `INTO`, `Lock`, dangerous `pg_*` functions, and enforces `LIMIT <= 1000`), backed by separate `nl2sql_ro` (`SELECT` only + `statement_timeout = 3000ms`) and `nl2sql_logger` (`INSERT` only on `query_logs`) PostgreSQL roles.

## Quickstart

### 1. Environment & Offline Dataset Smoketest
```bash
python -m venv .venv
pip install -r requirements.txt
python -m training.prepare_dataset --smoketest
```

### 2. QLoRA Dry-Run & Fine-Tuning (Colab/Kaggle GPU)
```bash
# Local CPU/GPU batch-masking check (pass --model-override for a local model dir)
python -m training.train_qlora --dry-run --smoketest --model-override <local_model_dir>

# Full Spider preparation & QLoRA training on GPU (auto-detects bf16 vs T4 fp16 fallback)
python -m training.prepare_dataset --db-dir data/spider/database
python -m training.train_qlora
```

### 3. 3-Way Evaluation Harness
```bash
# Offline smoketest verification
python -m eval.evaluate --smoketest --mock-inference

# Full 3-way evaluation (Base Zero-Shot, Base 3-Shot, QLoRA Fine-Tuned)
python -m eval.evaluate --adapter-dir outputs/qwen2.5-3b-nl2sql-qlora
```

### 4. Docker Compose Microservice
```bash
cp .env.example .env
docker compose up -d --build
curl -f http://localhost:8000/health
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "How many employees are there?"}'
docker compose down
```

## Benchmarks

All benchmark metrics (Execution Accuracy %, Valid SQL %, Raw Valid SQL %, P50/P95 latency, and peak GPU VRAM) are computed dynamically by `eval/evaluate.py` across `base_zero_shot`, `base_3_shot`, and `qlora_finetuned` and published directly to:

- [eval/results/benchmark_summary.md](eval/results/benchmark_summary.md)
- [eval/results/benchmark_summary.json](eval/results/benchmark_summary.json)

## Verification & Linting
```bash
ruff check .
pytest -v
```
