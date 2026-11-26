"""FastAPI microservice integration tests with mock inference and mock DB."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.inference import QLoRAPredictor, create_predictor
from app.main import create_app


@dataclass
class FakeDB:
    healthy: bool = True
    executed_sql: list[str] = field(default_factory=list)
    execute_errors: list[Exception] = field(default_factory=list)
    logs: list[dict[str, Any]] = field(default_factory=list)
    foreign_keys: list[dict[str, str]] = field(default_factory=list)
    schema_ddl: str = "CREATE TABLE orders (id integer PRIMARY KEY, customer text, amount double precision);"
    schema_details: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {
                "name": "orders",
                "columns": [
                    {"name": "id", "data_type": "integer", "is_nullable": False, "is_primary_key": True},
                    {"name": "customer", "data_type": "text", "is_nullable": False, "is_primary_key": False},
                    {"name": "amount", "data_type": "double precision", "is_nullable": True, "is_primary_key": False},
                ],
            }
        ]
    )

    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def ping(self) -> bool:
        return self.healthy

    async def fetch_schema_ddl(self) -> str:
        return self.schema_ddl

    async def fetch_schema_details(self) -> list[dict[str, Any]]:
        return self.schema_details

    async def fetch_foreign_keys(self) -> list[dict[str, str]]:
        return self.foreign_keys

    async def fetch_history(self, limit: int = 25) -> list[dict[str, Any]]:
        return list(reversed(self.logs))[:limit]

    async def execute_readonly(self, sql: str) -> tuple[list[str], list[list[Any]]]:
        self.executed_sql.append(sql)
        if self.execute_errors:
            raise self.execute_errors.pop(0)
        return ["total_count"], [[42]]

    async def log_query(
        self,
        question: str,
        generated_sql: str,
        status: str,
        latency_ms: float,
        error_message: str | None = None,
    ) -> None:
        self.logs.append(
            {
                "id": len(self.logs) + 1,
                "created_at": "2026-11-26T10:00:00+00:00",
                "question": question,
                "generated_sql": generated_sql,
                "status": status,
                "latency_ms": latency_ms,
                "error_message": error_message,
            }
        )


class StubPredictor:
    mode = "mock"

    def __init__(self, initial_sql: str, repaired_sqls: str | list[str] = "SELECT * FROM orders") -> None:
        self._initial_sql = initial_sql
        self._repaired_queue = [repaired_sqls] if isinstance(repaired_sqls, str) else list(repaired_sqls)
        self.seen_schema_ddls: list[str] = []
        self.repair_calls: list[tuple[str, str, str, str]] = []

    def generate(self, question: str, schema_ddl: str) -> str:
        del question
        self.seen_schema_ddls.append(schema_ddl)
        return self._initial_sql

    def repair(self, question: str, schema_ddl: str, failed_sql: str, error_message: str) -> str:
        self.repair_calls.append((question, schema_ddl, failed_sql, error_message))
        if len(self._repaired_queue) > 1:
            return self._repaired_queue.pop(0)
        return self._repaired_queue[0]


def test_health_endpoint_and_cors() -> None:
    db = FakeDB(healthy=True)
    app = create_app(db=db, predictor=create_predictor(mode="mock"))
    with TestClient(app) as client:
        resp = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "inference_mode": "mock", "db_connected": True}
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_schema_endpoint() -> None:
    db = FakeDB()
    app = create_app(db=db, predictor=create_predictor(mode="mock"))
    with TestClient(app) as client:
        resp = client.get("/schema")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["tables"]) == 1
    assert body["tables"][0]["name"] == "orders"
    assert body["tables"][0]["columns"][0] == {"name": "id", "data_type": "integer", "is_nullable": False}


def test_query_and_history_endpoints_end_to_end(monkeypatch) -> None:
    monkeypatch.setenv("INFERENCE_MODE", "mock")
    db = FakeDB()
    app = create_app(db=db, predictor=create_predictor())
    with TestClient(app) as client:
        resp = client.post("/query", json={"question": "How many orders are there?"})
        hist = client.get("/history?limit=10")

    assert resp.status_code == 200
    body = resp.json()
    assert body["sql"] == "SELECT COUNT(*) AS total_count FROM orders LIMIT 100"
    assert body["columns"] == ["total_count"]
    assert body["rows"] == [[42]]
    assert body["row_count"] == 1
    assert body["latency_ms"] >= 0.0
    assert body["was_repaired"] is False
    assert body["repair_attempts"] == 0
    assert body["linked_tables"] == ["orders"]
    assert db.executed_sql == ["SELECT COUNT(*) AS total_count FROM orders LIMIT 100"]

    assert hist.status_code == 200
    items = hist.json()["items"]
    assert len(items) == 1
    assert items[0]["status"] == "success"
    assert items[0]["question"] == "How many orders are there?"


def test_query_applies_schema_linking_and_injects_fk_ddl() -> None:
    db = FakeDB(
        schema_details=[
            {
                "name": "departments",
                "columns": [
                    {"name": "id", "data_type": "integer", "is_nullable": False, "is_primary_key": True},
                    {"name": "name", "data_type": "text", "is_nullable": False, "is_primary_key": False},
                ],
            },
            {
                "name": "suppliers",
                "columns": [
                    {"name": "id", "data_type": "integer", "is_nullable": False, "is_primary_key": True},
                    {"name": "country", "data_type": "text", "is_nullable": False, "is_primary_key": False},
                ],
            },
            {
                "name": "products",
                "columns": [
                    {"name": "id", "data_type": "integer", "is_nullable": False, "is_primary_key": True},
                    {"name": "supplier_id", "data_type": "integer", "is_nullable": False, "is_primary_key": False},
                ],
            },
            {
                "name": "orders",
                "columns": [
                    {"name": "id", "data_type": "integer", "is_nullable": False, "is_primary_key": True},
                    {"name": "product_id", "data_type": "integer", "is_nullable": False, "is_primary_key": False},
                ],
            },
        ],
        foreign_keys=[
            {"table": "products", "column": "supplier_id", "ref_table": "suppliers", "ref_column": "id"},
            {"table": "orders", "column": "product_id", "ref_table": "products", "ref_column": "id"},
        ],
    )
    predictor = StubPredictor("SELECT COUNT(*) FROM orders")
    app = create_app(db=db, predictor=predictor)
    with TestClient(app) as client:
        resp = client.post("/query", json={"question": "How many orders per supplier country?"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["linked_tables"] == ["suppliers", "products", "orders"]
    ddl = predictor.seen_schema_ddls[0]
    assert "FOREIGN KEY (supplier_id) REFERENCES suppliers(id)" in ddl
    assert "FOREIGN KEY (product_id) REFERENCES products(id)" in ddl
    assert "CREATE TABLE departments" not in ddl


def test_history_endpoint_validates_limit() -> None:
    db = FakeDB()
    app = create_app(db=db, predictor=create_predictor(mode="mock"))
    with TestClient(app) as client:
        resp = client.get("/history?limit=0")
    assert resp.status_code == 422


def test_query_endpoint_blocks_guard_violation_and_logs_rejection() -> None:
    db = FakeDB()
    bad_sql = "WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d"
    predictor = StubPredictor(bad_sql)
    app = create_app(db=db, predictor=predictor)
    with TestClient(app) as client:
        resp = client.post(
            "/query",
            json={"question": "Delete orders", "schema_ddl": "CREATE TABLE orders (id INT);"},
        )

    assert resp.status_code == 400
    assert "SQL guard rejected query" in resp.json()["detail"]["error"]
    assert predictor.repair_calls == []
    assert db.executed_sql == []
    assert len(db.logs) == 1
    assert db.logs[0]["status"] == "rejected"
    assert db.logs[0]["error_message"] is not None


def test_query_self_corrects_after_postgres_error() -> None:
    db = FakeDB(execute_errors=[RuntimeError('column "orders.customer" must appear in the GROUP BY clause')])
    predictor = StubPredictor(
        initial_sql="SELECT customer, COUNT(*) FROM orders",
        repaired_sqls="SELECT customer, COUNT(*) AS order_count FROM orders GROUP BY customer",
    )
    app = create_app(db=db, predictor=predictor)
    with TestClient(app) as client:
        resp = client.post("/query", json={"question": "Count orders per customer"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["was_repaired"] is True
    assert body["repair_attempts"] == 1
    assert body["linked_tables"] == ["orders"]
    assert body["sql"] == "SELECT customer, COUNT(*) AS order_count FROM orders GROUP BY customer LIMIT 100"
    assert len(predictor.repair_calls) == 1
    assert "GROUP BY clause" in predictor.repair_calls[0][3]
    assert db.executed_sql == [
        "SELECT customer, COUNT(*) FROM orders LIMIT 100",
        "SELECT customer, COUNT(*) AS order_count FROM orders GROUP BY customer LIMIT 100",
    ]
    assert len(db.logs) == 1
    assert db.logs[0]["status"] == "success"
    assert db.logs[0]["generated_sql"] == body["sql"]


def test_query_blocks_unsafe_repaired_sql_with_400() -> None:
    db = FakeDB(execute_errors=[RuntimeError('column "missing_col" does not exist')])
    predictor = StubPredictor(
        initial_sql="SELECT missing_col FROM orders",
        repaired_sqls="DROP TABLE orders",
    )
    app = create_app(db=db, predictor=predictor)
    with TestClient(app) as client:
        resp = client.post("/query", json={"question": "List orders"})

    assert resp.status_code == 400
    assert "SQL guard rejected query" in resp.json()["detail"]["error"]
    assert len(predictor.repair_calls) == 1
    assert db.executed_sql == ["SELECT missing_col FROM orders LIMIT 100"]
    assert len(db.logs) == 1
    assert db.logs[0]["status"] == "rejected"


def test_query_returns_500_with_generated_sql_after_default_two_retries() -> None:
    db = FakeDB(
        execute_errors=[
            RuntimeError('column "bad_col_1" does not exist'),
            RuntimeError('column "bad_col_2" does not exist'),
            RuntimeError('column "bad_col_3" does not exist'),
        ]
    )
    predictor = StubPredictor(
        initial_sql="SELECT bad_col_1 FROM orders",
        repaired_sqls=["SELECT bad_col_2 FROM orders", "SELECT bad_col_3 FROM orders"],
    )
    app = create_app(db=db, predictor=predictor)
    with TestClient(app) as client:
        resp = client.post("/query", json={"question": "List orders"})

    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert detail["error"] == "Database execution failed"
    assert 'column "bad_col_3" does not exist' in detail["reason"]
    assert detail["generated_sql"] == "SELECT bad_col_3 FROM orders LIMIT 100"
    assert len(predictor.repair_calls) == 2
    assert len(db.executed_sql) == 3
    assert len(db.logs) == 1
    assert db.logs[0]["status"] == "error"
    assert db.logs[0]["generated_sql"] == "SELECT bad_col_3 FROM orders LIMIT 100"


def test_mock_predictor_destructive_prompt_triggers_guard() -> None:
    db = FakeDB()
    app = create_app(db=db, predictor=create_predictor(mode="mock"))
    with TestClient(app) as client:
        resp = client.post("/query", json={"question": "Drop the orders table"})
    assert resp.status_code == 400
    assert "SQL guard rejected query" in resp.json()["detail"]["error"]
    assert db.executed_sql == []
    assert db.logs[0]["status"] == "rejected"


def test_query_endpoint_rejects_blank_question_with_422() -> None:
    db = FakeDB()
    app = create_app(db=db, predictor=create_predictor(mode="mock"))
    with TestClient(app) as client:
        resp = client.post("/query", json={"question": "   "})
    assert resp.status_code == 422
    assert db.executed_sql == []


def test_qlora_predictor_prompts_match_generate_and_repair(monkeypatch) -> None:
    from training.prepare_dataset import SYSTEM_PROMPT

    captured: list[list[dict[str, str]]] = []

    def fake_greedy(_model: Any, _tokenizer: Any, messages: list[dict[str, str]]) -> tuple[str, float]:
        captured.append(messages)
        return "```sql\nSELECT COUNT(*) FROM orders\n```", 1.0

    monkeypatch.setattr("eval.evaluate.generate_sql_greedy", fake_greedy)
    predictor = object.__new__(QLoRAPredictor)
    predictor._model = None
    predictor._tokenizer = None

    gen_sql = predictor.generate("Count orders", "CREATE TABLE orders (id integer PRIMARY KEY);")
    rep_sql = predictor.repair(
        "Count orders",
        "CREATE TABLE orders (id integer PRIMARY KEY);",
        "SELECT id, COUNT(*) FROM orders",
        'column "orders.id" must appear in the GROUP BY clause',
    )

    assert gen_sql == "SELECT COUNT(*) FROM orders"
    assert rep_sql == "SELECT COUNT(*) FROM orders"
    assert captured[0][0]["content"] == SYSTEM_PROMPT
    assert captured[0][1]["content"] == "Schema:\nCREATE TABLE orders (id integer PRIMARY KEY);\n\nQuestion:\nCount orders"
    assert "EXTRACT(EPOCH FROM" in captured[1][0]["content"]
    assert "GROUP BY" in captured[1][0]["content"]
    assert "FROM/JOIN" in captured[1][0]["content"]


def test_query_enriches_missing_column_error_with_owner_hint() -> None:
    db = FakeDB(
        schema_details=[
            {
                "name": "customers",
                "columns": [
                    {"name": "id", "data_type": "integer", "is_nullable": False, "is_primary_key": True},
                    {"name": "email", "data_type": "text", "is_nullable": False, "is_primary_key": False},
                ],
            },
            {
                "name": "suppliers",
                "columns": [
                    {"name": "id", "data_type": "integer", "is_nullable": False, "is_primary_key": True},
                    {"name": "country", "data_type": "text", "is_nullable": False, "is_primary_key": False},
                ],
            },
            {
                "name": "products",
                "columns": [
                    {"name": "id", "data_type": "integer", "is_nullable": False, "is_primary_key": True},
                    {"name": "supplier_id", "data_type": "integer", "is_nullable": False, "is_primary_key": False},
                ],
            },
            {
                "name": "orders",
                "columns": [
                    {"name": "id", "data_type": "integer", "is_nullable": False, "is_primary_key": True},
                    {"name": "product_id", "data_type": "integer", "is_nullable": False, "is_primary_key": False},
                ],
            },
        ],
        foreign_keys=[
            {"table": "products", "column": "supplier_id", "ref_table": "suppliers", "ref_column": "id"},
            {"table": "orders", "column": "product_id", "ref_table": "products", "ref_column": "id"},
        ],
        execute_errors=[RuntimeError("column o.country does not exist")],
    )
    predictor = StubPredictor(
        initial_sql="SELECT o.country, COUNT(*) FROM orders o GROUP BY o.country",
        repaired_sqls=(
            "SELECT s.country, COUNT(*) FROM orders o "
            "JOIN products p ON o.product_id = p.id "
            "JOIN suppliers s ON p.supplier_id = s.id GROUP BY s.country"
        ),
    )
    app = create_app(db=db, predictor=predictor)
    with TestClient(app) as client:
        resp = client.post("/query", json={"question": "Count orders by supplier country"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["was_repaired"] is True
    assert "JOIN PATHS:\n- products.supplier_id = suppliers.id\n- orders.product_id = products.id" in predictor.seen_schema_ddls[0]
    repair_err = predictor.repair_calls[0][3]
    assert "column o.country does not exist" in repair_err
    assert "Schema hint: Column 'country' belongs to table(s): suppliers." in repair_err
    assert "Join the owning table via its declared foreign key instead of referencing o.country." in repair_err


def test_qlora_predictor_accepts_hf_repo_id_and_local_dir(monkeypatch, tmp_path: Path) -> None:
    captured_adapters: list[Any] = []

    def fake_loader(_cfg: Any, adapter_dir: str | Path | None = None) -> tuple[None, None]:
        captured_adapters.append(adapter_dir)
        return None, None

    monkeypatch.setattr("eval.evaluate.load_hf_model_and_tokenizer", fake_loader)
    monkeypatch.setenv("INFERENCE_MODE", "qlora")
    monkeypatch.setenv("ADAPTER_DIR", "yassinelaabidi0/qwen2.5-3b-nl2sql-qlora")

    predictor = create_predictor()
    assert isinstance(predictor, QLoRAPredictor)
    assert captured_adapters[0] == "yassinelaabidi0/qwen2.5-3b-nl2sql-qlora"

    local_dir = tmp_path / "local_adapter"
    local_dir.mkdir()
    create_predictor(mode="qlora", adapter_dir=local_dir)
    assert captured_adapters[1] == local_dir

    with pytest.raises(FileNotFoundError):
        create_predictor(mode="qlora", adapter_dir=tmp_path / "missing_dir")

    with pytest.raises(FileNotFoundError):
        create_predictor(mode="qlora", adapter_dir="outputs/nonexistent_local_adapter")
