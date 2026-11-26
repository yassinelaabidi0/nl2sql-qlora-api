"""FastAPI microservice exposing /health, /schema, /history, and hardened /query endpoints."""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from app.db import AsyncPostgresClient, DatabaseProtocol
from app.guard import SQLGuardError, validate_and_normalize_sql
from app.inference import PredictorProtocol, create_predictor
from app.schemas import (
    HealthResponse,
    HistoryResponse,
    QueryRequest,
    QueryResponse,
    SchemaResponse,
)


def _resolve_max_sql_retries(override: int | None = None) -> int:
    if override is not None:
        return max(0, override)
    raw = os.getenv("MAX_SQL_RETRIES", "1").strip()
    return max(0, int(raw))


def create_app(
    db: DatabaseProtocol | None = None,
    predictor: PredictorProtocol | None = None,
    max_sql_retries: int | None = None,
) -> FastAPI:
    """Build FastAPI app with optional injected DB/predictor for isolated tests."""

    @asynccontextmanager
    async def lifespan(fastapi_app: FastAPI):
        managed_db = db is None
        eff_db = db or AsyncPostgresClient.from_env()
        eff_pred = predictor or create_predictor()
        if managed_db:
            await eff_db.connect()
        fastapi_app.state.db = eff_db
        fastapi_app.state.predictor = eff_pred
        try:
            yield
        finally:
            if managed_db:
                await eff_db.close()

    fastapi_app = FastAPI(title="NL-to-SQL Hardened Microservice", version="0.1.0", lifespan=lifespan)

    raw_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173")
    origins = [origin.strip() for origin in raw_origins.split(",") if origin.strip()]
    fastapi_app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @fastapi_app.get("/health", response_model=HealthResponse)
    async def health(request: Request) -> HealthResponse:
        active_db: DatabaseProtocol = request.app.state.db
        active_pred: PredictorProtocol = request.app.state.predictor
        db_ok = await active_db.ping()
        return HealthResponse(
            status="ok" if db_ok else "degraded",
            inference_mode=active_pred.mode,
            db_connected=db_ok,
        )

    @fastapi_app.get("/schema", response_model=SchemaResponse)
    async def schema(request: Request) -> SchemaResponse:
        active_db: DatabaseProtocol = request.app.state.db
        tables = await active_db.fetch_schema_details()
        return SchemaResponse(tables=tables)

    @fastapi_app.get("/history", response_model=HistoryResponse)
    async def history(
        request: Request,
        limit: int = Query(default=25, ge=1, le=200),
    ) -> HistoryResponse:
        active_db: DatabaseProtocol = request.app.state.db
        items = await active_db.fetch_history(limit=limit)
        return HistoryResponse(items=items)

    @fastapi_app.post("/query", response_model=QueryResponse)
    async def query(payload: QueryRequest, request: Request) -> QueryResponse:
        active_db: DatabaseProtocol = request.app.state.db
        active_pred: PredictorProtocol = request.app.state.predictor
        t0 = time.perf_counter()

        async def validate_or_abort(candidate_sql: str) -> str:
            try:
                return validate_and_normalize_sql(candidate_sql)
            except SQLGuardError as exc:
                latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                await active_db.log_query(payload.question, candidate_sql, "rejected", latency_ms, str(exc))
                raise HTTPException(
                    status_code=400,
                    detail={"error": "SQL guard rejected query", "reason": str(exc)},
                ) from exc

        schema_ddl = payload.schema_ddl or await active_db.fetch_schema_ddl()
        raw_sql = await asyncio.to_thread(active_pred.generate, payload.question, schema_ddl)
        safe_sql = await validate_or_abort(raw_sql)

        eff_retries = _resolve_max_sql_retries(max_sql_retries)
        repair_attempts = 0

        while True:
            try:
                columns, rows = await active_db.execute_readonly(safe_sql)
                break
            except Exception as exc:
                if repair_attempts >= eff_retries:
                    latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                    await active_db.log_query(payload.question, safe_sql, "error", latency_ms, str(exc))
                    raise HTTPException(
                        status_code=500,
                        detail={
                            "error": "Database execution failed",
                            "reason": str(exc),
                            "generated_sql": safe_sql,
                        },
                    ) from exc

                repair_attempts += 1
                repaired_raw_sql = await asyncio.to_thread(
                    active_pred.repair,
                    payload.question,
                    schema_ddl,
                    safe_sql,
                    str(exc),
                )
                safe_sql = await validate_or_abort(repaired_raw_sql)

        latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        await active_db.log_query(payload.question, safe_sql, "success", latency_ms, None)
        return QueryResponse(
            question=payload.question,
            sql=safe_sql,
            columns=columns,
            rows=rows,
            row_count=len(rows),
            latency_ms=latency_ms,
            was_repaired=repair_attempts > 0,
            repair_attempts=repair_attempts,
        )

    return fastapi_app


app = create_app()
