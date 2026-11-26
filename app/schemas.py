"""Strict Pydantic v2 request and response schemas for the NL-to-SQL API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(..., min_length=1, max_length=1000)
    schema_ddl: str | None = Field(default=None, min_length=1, max_length=20000)

    @field_validator("question")
    @classmethod
    def _strip_non_empty_question(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("question must not be blank.")
        return cleaned


class QueryResponse(BaseModel):
    question: str
    sql: str
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    latency_ms: float
    was_repaired: bool = False
    repair_attempts: int = 0
    linked_tables: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    inference_mode: str
    db_connected: bool


class ColumnInfo(BaseModel):
    name: str
    data_type: str
    is_nullable: bool


class TableSchema(BaseModel):
    name: str
    columns: list[ColumnInfo]


class SchemaResponse(BaseModel):
    tables: list[TableSchema]


class HistoryEntry(BaseModel):
    id: int
    created_at: str
    question: str
    generated_sql: str
    status: str
    latency_ms: float
    error_message: str | None = None


class HistoryResponse(BaseModel):
    items: list[HistoryEntry]
