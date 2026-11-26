"""FastAPI microservice integration tests with mock inference and mock DB."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi.testclient import TestClient

from app.inference import create_predictor
from app.main import create_app


@dataclass
class FakeDB:
    healthy: bool = True
    executed_sql: list[str] = field(default_factory=list)
    logs: list[dict[str, Any]] = field(default_factory=list)
    schema_ddl: str = "CREATE TABLE orders (id integer, customer text, amount double precision);"
    schema_details: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {
                "name": "orders",
                "columns": [
                    {"name": "id", "data_type": "integer", "is_nullable": False},
                    {"name": "customer", "data_type": "text", "is_nullable": False},
                    {"name": "amount", "data_type": "double precision", "is_nullable": True},
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

    async def fetch_history(self, limit: int = 25) -> list[dict[str, Any]]:
        return list(reversed(self.logs))[:limit]

    async def execute_readonly(self, sql: str) -> tuple[list[str], list[list[Any]]]:
        self.executed_sql.append(sql)
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


class UnsafeStubPredictor:
    mode = "mock"

    def __init__(self, bad_sql: str) -> None:
        self._bad_sql = bad_sql

    def generate(self, question: str, schema_ddl: str) -> str:
        return self._bad_sql


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
    assert db.executed_sql == ["SELECT COUNT(*) AS total_count FROM orders LIMIT 100"]

    assert hist.status_code == 200
    items = hist.json()["items"]
    assert len(items) == 1
    assert items[0]["status"] == "success"
    assert items[0]["question"] == "How many orders are there?"


def test_history_endpoint_validates_limit() -> None:
    db = FakeDB()
    app = create_app(db=db, predictor=create_predictor(mode="mock"))
    with TestClient(app) as client:
        resp = client.get("/history?limit=0")
    assert resp.status_code == 422


def test_query_endpoint_blocks_guard_violation_and_logs_rejection() -> None:
    db = FakeDB()
    bad_sql = "WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d"
    app = create_app(db=db, predictor=UnsafeStubPredictor(bad_sql))
    with TestClient(app) as client:
        resp = client.post(
            "/query",
            json={"question": "Delete orders", "schema_ddl": "CREATE TABLE orders (id INT);"},
        )

    assert resp.status_code == 400
    assert "SQL guard rejected query" in resp.json()["detail"]["error"]
    assert db.executed_sql == []
    assert len(db.logs) == 1
    assert db.logs[0]["status"] == "rejected"
    assert db.logs[0]["error_message"] is not None


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
