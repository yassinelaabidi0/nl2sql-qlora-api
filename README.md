# NL2SQL Workbench — Local QLoRA LLM & Hardened FastAPI Microservice

Full-stack Natural-Language-to-SQL workbench powered by a 4-bit NF4 QLoRA-fine-tuned `Qwen/Qwen2.5-3B-Instruct` model, served through an AST-validated FastAPI + PostgreSQL microservice with foreign-key schema linking, bounded PostgreSQL self-correction, and a React 19 + TypeScript UI.

## Architecture

```mermaid
flowchart TD
    UI["React Workbench UI<br/>frontend Vite Tailwind"] -->|"GET /schema · GET /history"| API["FastAPI Microservice<br/>app/main.py"]
    UI -->|"POST /query"| API
    API -->|"Introspect PK + FK<br/>pg_catalog.pg_constraint"| Linker["Schema Linker<br/>app/schema_linker.py<br/>Lexical Seed + BFS Bridge"]
    Linker -->|"Pruned DDL + JOIN PATHS"| LLM["Qwen2.5-3B QLoRA / MockPredictor<br/>Training-Aligned Prompt"]
    LLM -->|"Candidate SQL"| Guard["AST Security Guard<br/>app/guard.py<br/>SQLGlot SELECT + LIMIT"]
    Guard -->|"SQLGuardError - HTTP 400<br/>No Retry"| AuditReject["nl2sql_logger<br/>INSERT query_logs - rejected"]
    Guard -->|"Validated SQL"| Exec["nl2sql_ro<br/>Read-Only SELECT - 3s timeout"]
    Exec -->|"Postgres Runtime Error<br/>retries left MAX_SQL_RETRIES=2"| Hint["Enrich Missing Column Error<br/>Schema Column-Owner Hint"]
    Hint --> Repair["predictor.repair<br/>Postgres Rules + Alias Check"]
    Repair --> Guard
    Exec -->|"Execution Failed<br/>retries exhausted - HTTP 500"| AuditErr["nl2sql_logger<br/>INSERT query_logs - error"]
    Exec -->|"Success"| AuditOK["nl2sql_logger<br/>INSERT query_logs - success"]
    AuditOK --> Resp["JSON QueryResponse<br/>was_repaired + linked_tables"]
    Resp --> UI
```

### Design, Guardrails & Pipeline Engineering
- **Schema-Disjoint Splits:** `training/prepare_dataset.py` extracts compact `CREATE TABLE` DDL from `sqlite_master` and enforces zero `db_id` overlap across train/validation splits.
- **Completion-Only Loss:** `training/train_qlora.py` uses TRL `SFTConfig(completion_only_loss=True)` with `prompt`/`completion` formatting so prompt/DDL tokens are masked (`-100`) during QLoRA training.
- **Read-Only Evaluation:** `eval/sqlite_exec.py` runs SQLite `?mode=ro` with a `set_progress_handler` 3.0s monotonic timeout and duplicate-preserving multiset (or `ORDER BY` list) comparison.
- **Defense-in-Depth SQL Serving:** `app/guard.py` validates the full Postgres AST via `sqlglot` (single `Select`/`Union`, blocks writable CTEs, DML/DDL, `INTO`, `Lock`, dangerous `pg_*` functions, and enforces `LIMIT <= 1000`), backed by separate `nl2sql_ro` (`SELECT` only + `statement_timeout = 3000ms`) and `nl2sql_logger` (`SELECT, INSERT` on `query_logs` only) PostgreSQL roles.
- **Live Catalog Introspection & FK Schema Linking (`app/db.py`, `app/schema_linker.py`):** Queries `pg_catalog.pg_constraint` (accessible to `SELECT`-only roles unlike `information_schema.table_constraints`) for primary and foreign keys, then prunes multi-domain schemas via lexical scoring and undirected BFS shortest-path bridging to prevent cross-domain join hallucinations and shrink prompt context.
- **Bounded PostgreSQL Self-Correction (`app/main.py`, `app/inference.py`):** Retries runtime PostgreSQL failures up to `MAX_SQL_RETRIES=2` times with `Schema hint:` column-ownership diagnostics via `predictor.repair()`, re-validates every repaired query through `app/guard.py`, and aborts `SQLGuardError` security violations immediately with `HTTP 400` and zero retries.
- **NL2SQL Workbench UI (`frontend/`):** React 19 + TypeScript interface featuring a live searchable Schema Explorer (`GET /schema`), query runner with `Auto-repaired` badges and collapsible failed-SQL diagnostics, client-side filtering/sorting with CSV & JSON exports, dark/light theme persistence, and an Audit & History drawer (`GET /history`).

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

### 4. Full-Stack Microservice & Local Workbench

**Option A — Docker Compose Full Stack (`http://localhost:3000`):**
```bash
cp .env.example .env
docker compose up -d --build
curl -f http://localhost:8000/health
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "How many employees are there?"}'
docker compose down
```
Nginx serves the built React workbench on `http://localhost:3000` and proxies `/api/*` requests directly to `api:8000`.

**Option B — Local GPU Inference + Vite Dev Server (`http://localhost:5173`):**
```bash
# Terminal 1: Start Postgres only, then run Uvicorn against the local QLoRA adapter
docker compose up -d postgres
INFERENCE_MODE=qlora \
READONLY_DATABASE_URL=postgresql://nl2sql_ro:nl2sql_ro@localhost:5432/nl2sql \
LOG_DATABASE_URL=postgresql://nl2sql_logger:nl2sql_logger@localhost:5432/nl2sql \
MAX_SQL_RETRIES=2 \
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Terminal 2: Start the React dev server (proxies /api -> http://localhost:8000)
cd frontend
npm install
npm run dev
```

**Optional 11-Table Stress-Test Seed (`db/complex_seed.sql`):**
`db/init.sql` initializes a 3-table HR sample schema (`departments`, `employees`, `sales`) on first boot. To also seed the 8-table e-commerce & logistics schema (`categories`, `suppliers`, `products`, `customers`, `orders`, `order_items`, `shipments`, `reviews`) for multi-domain FK linking tests:
```bash
docker compose exec -T postgres psql -U postgres -d nl2sql < db/complex_seed.sql
```

## Benchmarks

Evaluated on the full held-out Spider validation set (**1,034 examples across 20 unseen schemas**) using a Kaggle Tesla T4 GPU (`15 GB` VRAM, greedy decoding `do_sample=False`, `3.0s` read-only SQLite execution timeout).

### 3-Way Evaluation Results

| Mode | EX (%) | Valid SQL (%) | Raw Valid SQL (%) | P50 Latency (ms) | P95 Latency (ms) | Peak VRAM (MB) |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| `base_zero_shot` | 53.68 | 83.17 | 83.17 | 2774.77 | 5386.83 | 2172.88 |
| `base_3_shot` | 51.06 | 81.82 | 81.82 | 3687.51 | 6538.00 | 2684.80 |
| `qlora_finetuned` | **70.12** | **91.10** | **91.10** | 3187.21 | 9793.53 | 2285.94 |

### QLoRA Training Summary (Kaggle T4, `float16` + 4-bit NF4)

- **Steps:** `1,314` (`completion_only_loss=true`)
- **Train Loss:** `0.1033` (`0.10331352102702067`) | **Eval Loss:** `0.3782` (`0.37822282314300537`)
- **Training Peak VRAM:** `5,221.55 MB`

### Key Takeaways

- **+16.44 pp Execution Accuracy** over zero-shot (`53.68%` → `70.12%`) and **+19.06 pp** over 3-shot (`51.06%` → `70.12%`) on 20 unseen Spider schemas (`1,034` val examples).
- **+7.93 pp Valid SQL** improvement (`83.17%` → `91.10%`) with zero post-processing gap (`Raw Valid SQL% == Valid SQL%`).
- **Why QLoRA beats 3-shot prompting on a 3B model:** 3-shot drops EX accuracy (`-2.62 pp` vs. zero-shot) while increasing P50 latency (`+913 ms`, `2774.77 ms` → `3687.51 ms`) and Peak VRAM (`+512 MB`, `2172.88 MB` → `2684.80 MB`) from longer KV-cache context.

Full machine-readable outputs:
- [eval/results/benchmark_summary.md](eval/results/benchmark_summary.md)
- [eval/results/benchmark_summary.json](eval/results/benchmark_summary.json)
- [eval/results/training_summary.json](eval/results/training_summary.json)

## Verification & Linting
```bash
ruff check .
pytest -v
cd frontend && npm run build
```
