"""Async PostgreSQL client with separate read-only execution and audit log pools."""

from __future__ import annotations

import datetime as dt
import os
import uuid
from decimal import Decimal
from typing import Any, Protocol

import asyncpg

_QUERY_LOGS_DDL = """
CREATE TABLE IF NOT EXISTS query_logs (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    question TEXT NOT NULL,
    generated_sql TEXT NOT NULL,
    status TEXT NOT NULL,
    latency_ms DOUBLE PRECISION NOT NULL,
    error_message TEXT
);
"""


def _to_json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (dt.datetime, dt.date, dt.time, uuid.UUID)):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    return value


class DatabaseProtocol(Protocol):
    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    async def ping(self) -> bool: ...
    async def fetch_schema_ddl(self) -> str: ...
    async def execute_readonly(self, sql: str) -> tuple[list[str], list[list[Any]]]: ...
    async def log_query(
        self,
        question: str,
        generated_sql: str,
        status: str,
        latency_ms: float,
        error_message: str | None = None,
    ) -> None: ...


class AsyncPostgresClient:
    """Dual-pool asyncpg client: read-only role for NL2SQL, write role for query_logs."""

    def __init__(
        self,
        readonly_dsn: str,
        log_dsn: str,
        statement_timeout_ms: int = 3000,
    ) -> None:
        self.readonly_dsn = readonly_dsn
        self.log_dsn = log_dsn
        self.statement_timeout_ms = statement_timeout_ms
        self._ro_pool: asyncpg.Pool | None = None
        self._log_pool: asyncpg.Pool | None = None

    @classmethod
    def from_env(cls) -> AsyncPostgresClient:
        ro_dsn = os.getenv("READONLY_DATABASE_URL", "postgresql://nl2sql_ro:nl2sql_ro@localhost:5432/nl2sql")
        log_dsn = os.getenv("LOG_DATABASE_URL", os.getenv("DATABASE_URL", ro_dsn))
        timeout_ms = int(os.getenv("STATEMENT_TIMEOUT_MS", "3000"))
        return cls(readonly_dsn=ro_dsn, log_dsn=log_dsn, statement_timeout_ms=timeout_ms)

    async def connect(self) -> None:
        self._ro_pool = await asyncpg.create_pool(self.readonly_dsn, min_size=1, max_size=5)
        self._log_pool = await asyncpg.create_pool(self.log_dsn, min_size=1, max_size=3)
        async with self._log_pool.acquire() as conn:
            if await conn.fetchval("SELECT to_regclass('public.query_logs')") is None:
                await conn.execute(_QUERY_LOGS_DDL)

    async def close(self) -> None:
        if self._ro_pool is not None:
            await self._ro_pool.close()
        if self._log_pool is not None:
            await self._log_pool.close()

    async def ping(self) -> bool:
        if self._ro_pool is None:
            return False
        try:
            async with self._ro_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except (asyncpg.PostgresError, OSError):
            return False

    async def fetch_schema_ddl(self) -> str:
        if self._ro_pool is None:
            raise RuntimeError("Database pool is not initialized.")
        query = (
            "SELECT table_name, column_name, data_type "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name <> 'query_logs' "
            "ORDER BY table_name, ordinal_position"
        )
        async with self._ro_pool.acquire() as conn:
            rows = await conn.fetch(query)
        tables: dict[str, list[str]] = {}
        for row in rows:
            tables.setdefault(str(row["table_name"]), []).append(f"{row['column_name']} {row['data_type']}")
        if not tables:
            raise RuntimeError("No queryable tables found in public schema.")
        return "\n".join(f"CREATE TABLE {tbl} ({', '.join(cols)});" for tbl, cols in tables.items())

    async def execute_readonly(self, sql: str) -> tuple[list[str], list[list[Any]]]:
        if self._ro_pool is None:
            raise RuntimeError("Database pool is not initialized.")
        async with self._ro_pool.acquire() as conn, conn.transaction(readonly=True):
            await conn.execute(f"SET LOCAL statement_timeout = {int(self.statement_timeout_ms)}")
            stmt = await conn.prepare(sql)
            columns = [attr.name for attr in stmt.get_attributes()]
            records = await stmt.fetch()
            rows = [[_to_json_safe(val) for val in rec.values()] for rec in records]
            return columns, rows

    async def log_query(
        self,
        question: str,
        generated_sql: str,
        status: str,
        latency_ms: float,
        error_message: str | None = None,
    ) -> None:
        if self._log_pool is None:
            raise RuntimeError("Log database pool is not initialized.")
        async with self._log_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO query_logs (question, generated_sql, status, latency_ms, error_message) "
                "VALUES ($1, $2, $3, $4, $5)",
                question,
                generated_sql,
                status,
                latency_ms,
                error_message,
            )
