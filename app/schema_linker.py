"""Deterministic FK-graph schema linking and PostgreSQL DDL formatting."""

from __future__ import annotations

import re
from collections import defaultdict, deque
from collections.abc import Sequence
from typing import Any

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "between",
        "by",
        "each",
        "exclude",
        "excluding",
        "for",
        "from",
        "get",
        "group",
        "having",
        "how",
        "in",
        "into",
        "is",
        "list",
        "many",
        "most",
        "of",
        "on",
        "or",
        "per",
        "show",
        "than",
        "that",
        "the",
        "their",
        "this",
        "to",
        "top",
        "what",
        "where",
        "which",
        "who",
        "whose",
        "with",
        "without",
    }
)

_GENERIC_COLUMNS = frozenset({"id", "name", "created_at", "updated_at"})


def _singularize(token: str) -> str:
    if token == "statuses":
        return "status"
    if len(token) > 4 and token.endswith("ies"):
        return f"{token[:-3]}y"
    if len(token) > 4 and token.endswith(("sses", "xes", "zes", "ches", "shes")):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def _tokenize(text: str, drop_stopwords: bool = True) -> set[str]:
    raw_words = re.findall(r"[a-z0-9]+", text.lower())
    tokens: set[str] = set()
    for word in raw_words:
        if drop_stopwords and word in _STOPWORDS:
            continue
        tokens.add(word)
        singular = _singularize(word)
        if not (drop_stopwords and singular in _STOPWORDS):
            tokens.add(singular)
    return tokens


def _identifier_subtokens(identifier: str) -> list[str]:
    parts = [p for p in re.findall(r"[a-z0-9]+", identifier.lower()) if p]
    return [_singularize(p) for p in parts]


def _matches_table_name(table_name: str, q_tokens: set[str]) -> bool:
    lower = table_name.lower()
    singular = _singularize(lower)
    if lower in q_tokens or singular in q_tokens:
        return True
    parts = _identifier_subtokens(table_name)
    if len(parts) > 1:
        joined = "".join(parts)
        if joined in q_tokens or all(part in q_tokens for part in parts):
            return True
    return False


def _matching_columns(columns: Sequence[dict[str, Any]], q_tokens: set[str]) -> set[str]:
    matched: set[str] = set()
    for col in columns:
        col_name = str(col["name"]).lower()
        if col_name in _GENERIC_COLUMNS or col_name.endswith("_id"):
            continue
        singular = _singularize(col_name)
        if col_name in q_tokens or singular in q_tokens:
            matched.add(col_name)
            continue
        parts = [p for p in _identifier_subtokens(col_name) if p != "id"]
        if len(parts) > 1 and all(part in q_tokens for part in parts):
            matched.add(col_name)
    return matched


def _shortest_path(adj: dict[str, list[str]], start: str, goal: str) -> list[str]:
    if start == goal:
        return [start]
    visited = {start}
    queue: deque[list[str]] = deque([[start]])
    while queue:
        path = queue.popleft()
        node = path[-1]
        for neighbor in adj.get(node, []):
            if neighbor in visited:
                continue
            next_path = [*path, neighbor]
            if neighbor == goal:
                return next_path
            visited.add(neighbor)
            queue.append(next_path)
    return []


def link_schema(
    question: str,
    tables: list[dict[str, Any]],
    foreign_keys: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Prune tables to question-relevant seeds plus shortest-path FK bridge tables."""
    if not tables:
        return [], []

    q_tokens = _tokenize(question, drop_stopwords=True)
    scores: dict[str, float] = {}
    table_matched_cols: set[str] = set()

    for tbl in tables:
        name = str(tbl["name"])
        cols = tbl.get("columns", [])
        if _matches_table_name(name, q_tokens):
            scores[name] = 6.0 + len(_matching_columns(cols, q_tokens))
            table_matched_cols.update(_matching_columns(cols, q_tokens))
        else:
            scores[name] = 0.0

    for tbl in tables:
        name = str(tbl["name"])
        if scores[name] > 0.0:
            continue
        col_hits = _matching_columns(tbl.get("columns", []), q_tokens) - table_matched_cols
        if col_hits:
            scores[name] = float(len(col_hits))

    seeds = [str(tbl["name"]) for tbl in tables if scores.get(str(tbl["name"]), 0.0) > 0.0]
    if not seeds:
        return list(tables), list(foreign_keys)

    adj: dict[str, set[str]] = defaultdict(set)
    for fk in foreign_keys:
        src = str(fk["table"])
        dst = str(fk["ref_table"])
        if src != dst:
            adj[src].add(dst)
            adj[dst].add(src)
    sorted_adj = {node: sorted(neighbors) for node, neighbors in adj.items()}

    linked_names: set[str] = set(seeds)
    for i, src in enumerate(seeds):
        for dst in seeds[i + 1 :]:
            linked_names.update(_shortest_path(sorted_adj, src, dst))

    linked_tables = [tbl for tbl in tables if str(tbl["name"]) in linked_names]
    linked_fks = [
        fk
        for fk in foreign_keys
        if str(fk["table"]) in linked_names and str(fk["ref_table"]) in linked_names
    ]
    return linked_tables, linked_fks


def find_column_owners(column_name: str, tables: Sequence[dict[str, Any]]) -> list[str]:
    """Return table names containing column_name (case-insensitive)."""
    target = column_name.strip().lower()
    if not target:
        return []
    return [
        str(tbl["name"])
        for tbl in tables
        if any(str(col["name"]).lower() == target for col in tbl.get("columns", []))
    ]


def format_join_paths(foreign_keys: Sequence[dict[str, str]]) -> str:
    """Format foreign keys as explicit join paths, or empty string when none exist."""
    if not foreign_keys:
        return ""
    lines = [f"- {fk['table']}.{fk['column']} = {fk['ref_table']}.{fk['ref_column']}" for fk in foreign_keys]
    return "JOIN PATHS:\n" + "\n".join(lines)


def format_schema_ddl(
    tables: Sequence[dict[str, Any]],
    foreign_keys: Sequence[dict[str, str]],
) -> str:
    """Format tables and foreign keys into PostgreSQL CREATE TABLE DDL."""
    fks_by_table: dict[str, list[dict[str, str]]] = defaultdict(list)
    for fk in foreign_keys:
        fks_by_table[str(fk["table"])].append(fk)

    blocks: list[str] = []
    for tbl in tables:
        name = str(tbl["name"])
        cols = tbl.get("columns", [])
        pk_cols = [str(col["name"]) for col in cols if col.get("is_primary_key")]
        single_pk = len(pk_cols) == 1

        lines: list[str] = []
        for col in cols:
            col_name = str(col["name"])
            col_type = str(col["data_type"])
            parts = [col_name, col_type]
            if single_pk and col.get("is_primary_key"):
                parts.append("PRIMARY KEY")
            elif col.get("is_nullable") is False:
                parts.append("NOT NULL")
            lines.append(f"    {' '.join(parts)}")

        if len(pk_cols) > 1:
            lines.append(f"    PRIMARY KEY ({', '.join(pk_cols)})")

        for fk in fks_by_table.get(name, []):
            lines.append(
                f"    FOREIGN KEY ({fk['column']}) REFERENCES {fk['ref_table']}({fk['ref_column']})"
            )

        body = ",\n".join(lines)
        blocks.append(f"CREATE TABLE {name} (\n{body}\n);")

    ddl = "\n\n".join(blocks)
    join_paths = format_join_paths(foreign_keys)
    return f"{ddl}\n\n{join_paths}" if join_paths else ddl
