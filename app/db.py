"""Async PostgreSQL client with separate read-only execution and audit log pools."""

from __future__ import annotations

import datetime as dt
import os
import uuid
from decimal import Decimal
from typing import Any, Protocol

import asyncpg

from app.schema_linker import format_schema_ddl

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
    async def fetch_schema_details(self) -> list[dict[str, Any]]: ...
    async def fetch_foreign_keys(self) -> list[dict[str, str]]: ...
    async def fetch_history(self, limit: int = 25) -> list[dict[str, Any]]: ...
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

    async def fetch_schema_details(self) -> list[dict[str, Any]]:
        if self._ro_pool is None:
            raise RuntimeError("Database pool is not initialized.")
        col_query = (
            "SELECT table_name, column_name, data_type, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name <> 'query_logs' "
            "ORDER BY table_name, ordinal_position"
        )
        pk_query = (
            "SELECT rel.relname AS table_name, a.attname AS column_name "
            "FROM pg_catalog.pg_constraint AS con "
            "JOIN pg_catalog.pg_class AS rel ON rel.oid = con.conrelid "
            "JOIN pg_catalog.pg_namespace AS nsp ON nsp.oid = rel.relnamespace "
            "CROSS JOIN LATERAL UNNEST(con.conkey) WITH ORDINALITY AS k(attnum, ord) "
            "JOIN pg_catalog.pg_attribute AS a ON a.attrelid = con.conrelid AND a.attnum = k.attnum "
            "WHERE con.contype = 'p' "
            "AND nsp.nspname = 'public' "
            "AND rel.relname <> 'query_logs' "
            "AND has_table_privilege(rel.oid, 'SELECT')"
        )
        async with self._ro_pool.acquire() as conn:
            rows = await conn.fetch(col_query)
            pk_rows = await conn.fetch(pk_query)

        pk_columns = {(str(r["table_name"]), str(r["column_name"])) for r in pk_rows}
        tables: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            tbl = str(row["table_name"])
            col = str(row["column_name"])
            tables.setdefault(tbl, []).append(
                {
                    "name": col,
                    "data_type": str(row["data_type"]),
                    "is_nullable": str(row["is_nullable"]).upper() == "YES",
                    "is_primary_key": (tbl, col) in pk_columns,
                }
            )
        return [{"name": tbl, "columns": cols} for tbl, cols in tables.items()]

    async def fetch_foreign_keys(self) -> list[dict[str, str]]:
        """Query PostgreSQL foreign keys via pg_constraint (works under SELECT-only roles)."""
        if self._ro_pool is None:
            raise RuntimeError("Database pool is not initialized.")
        query = (
            "SELECT rel.relname AS table_name, "
            "       a.attname AS column_name, "
            "       ref.relname AS ref_table, "
            "       af.attname AS ref_column "
            "FROM pg_catalog.pg_constraint AS con "
            "JOIN pg_catalog.pg_class AS rel ON rel.oid = con.conrelid "
            "JOIN pg_catalog.pg_class AS ref ON ref.oid = con.confrelid "
            "JOIN pg_catalog.pg_namespace AS nsp ON nsp.oid = rel.relnamespace "
            "CROSS JOIN LATERAL UNNEST(con.conkey) WITH ORDINALITY AS k(attnum, ord) "
            "JOIN LATERAL UNNEST(con.confkey) WITH ORDINALITY AS fk(attnum, ord) ON fk.ord = k.ord "
            "JOIN pg_catalog.pg_attribute AS a ON a.attrelid = con.conrelid AND a.attnum = k.attnum "
            "JOIN pg_catalog.pg_attribute AS af ON af.attrelid = con.confrelid AND af.attnum = fk.attnum "
            "WHERE con.contype = 'f' "
            "AND nsp.nspname = 'public' "
            "AND rel.relname <> 'query_logs' "
            "AND ref.relname <> 'query_logs' "
            "AND has_table_privilege(rel.oid, 'SELECT') "
            "AND has_table_privilege(ref.oid, 'SELECT') "
            "ORDER BY rel.relname, con.conname, k.ord"
        )
        async with self._ro_pool.acquire() as conn:
            rows = await conn.fetch(query)
        return [
            {
                "table": str(row["table_name"]),
                "column": str(row["column_name"]),
                "ref_table": str(row["ref_table"]),
                "ref_column": str(row["ref_column"]),
            }
            for row in rows
        ]

    async def fetch_schema_ddl(self) -> str:
        details = await self.fetch_schema_details()
        if not details:
            raise RuntimeError("No queryable tables found in public schema.")
        foreign_keys = await self.fetch_foreign_keys()
        return format_schema_ddl(details, foreign_keys)

    async def fetch_history(self, limit: int = 25) -> list[dict[str, Any]]:
        if self._log_pool is None:
            raise RuntimeError("Log database pool is not initialized.")
        query = (
            "SELECT id, created_at, question, generated_sql, status, latency_ms, error_message "
            "FROM query_logs ORDER BY id DESC LIMIT $1"
        )
        async with self._log_pool.acquire() as conn:
            rows = await conn.fetch(query, limit)
        return [
            {
                "id": int(row["id"]),
                "created_at": str(_to_json_safe(row["created_at"])),
                "question": str(row["question"]),
                "generated_sql": str(row["generated_sql"]),
                "status": str(row["status"]),
                "latency_ms": float(row["latency_ms"]),
                "error_message": str(row["error_message"]) if row["error_message"] is not None else None,
            }
            for row in rows
        ]

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
