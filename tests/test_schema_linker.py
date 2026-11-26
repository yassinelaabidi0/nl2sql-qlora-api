"""Unit tests for deterministic FK-graph schema linking and DDL formatting."""

from __future__ import annotations

from typing import Any

from app.schema_linker import (
    find_column_owners,
    format_join_paths,
    format_schema_ddl,
    link_schema,
)


def _col(name: str, data_type: str = "text", nullable: bool = False, pk: bool = False) -> dict[str, Any]:
    return {
        "name": name,
        "data_type": data_type,
        "is_nullable": nullable,
        "is_primary_key": pk,
    }


def _combined_11_table_schema() -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    tables = [
        {"name": "departments", "columns": [_col("id", "integer", pk=True), _col("name"), _col("budget", "numeric")]},
        {
            "name": "employees",
            "columns": [
                _col("id", "integer", pk=True),
                _col("full_name"),
                _col("role"),
                _col("department_id", "integer"),
                _col("salary", "numeric"),
                _col("hired_at", "date"),
            ],
        },
        {
            "name": "sales",
            "columns": [
                _col("id", "integer", pk=True),
                _col("employee_id", "integer"),
                _col("region"),
                _col("quarter"),
                _col("amount", "numeric"),
            ],
        },
        {
            "name": "categories",
            "columns": [_col("id", "integer", pk=True), _col("name"), _col("parent_category_id", "integer", nullable=True)],
        },
        {
            "name": "suppliers",
            "columns": [
                _col("id", "integer", pk=True),
                _col("name"),
                _col("country"),
                _col("reliability_score", "numeric"),
            ],
        },
        {
            "name": "products",
            "columns": [
                _col("id", "integer", pk=True),
                _col("sku"),
                _col("name"),
                _col("category_id", "integer"),
                _col("supplier_id", "integer"),
                _col("unit_price", "numeric"),
                _col("cost_price", "numeric"),
                _col("stock_qty", "integer"),
                _col("is_active", "boolean"),
            ],
        },
        {
            "name": "customers",
            "columns": [
                _col("id", "integer", pk=True),
                _col("full_name"),
                _col("email"),
                _col("country"),
                _col("tier"),
                _col("signup_date", "date"),
            ],
        },
        {
            "name": "orders",
            "columns": [
                _col("id", "integer", pk=True),
                _col("customer_id", "integer"),
                _col("order_date", "timestamp"),
                _col("status"),
                _col("shipping_cost", "numeric"),
                _col("discount_pct", "numeric"),
            ],
        },
        {
            "name": "order_items",
            "columns": [
                _col("id", "integer", pk=True),
                _col("order_id", "integer"),
                _col("product_id", "integer"),
                _col("quantity", "integer"),
                _col("unit_price", "numeric"),
            ],
        },
        {
            "name": "shipments",
            "columns": [
                _col("id", "integer", pk=True),
                _col("order_id", "integer"),
                _col("carrier"),
                _col("warehouse"),
                _col("shipped_at", "timestamp"),
                _col("delivered_at", "timestamp", nullable=True),
                _col("delivery_status"),
            ],
        },
        {
            "name": "reviews",
            "columns": [
                _col("id", "integer", pk=True),
                _col("product_id", "integer"),
                _col("customer_id", "integer"),
                _col("rating", "integer"),
                _col("created_at", "date"),
            ],
        },
    ]
    foreign_keys = [
        {"table": "employees", "column": "department_id", "ref_table": "departments", "ref_column": "id"},
        {"table": "sales", "column": "employee_id", "ref_table": "employees", "ref_column": "id"},
        {"table": "categories", "column": "parent_category_id", "ref_table": "categories", "ref_column": "id"},
        {"table": "products", "column": "category_id", "ref_table": "categories", "ref_column": "id"},
        {"table": "products", "column": "supplier_id", "ref_table": "suppliers", "ref_column": "id"},
        {"table": "orders", "column": "customer_id", "ref_table": "customers", "ref_column": "id"},
        {"table": "order_items", "column": "order_id", "ref_table": "orders", "ref_column": "id"},
        {"table": "order_items", "column": "product_id", "ref_table": "products", "ref_column": "id"},
        {"table": "shipments", "column": "order_id", "ref_table": "orders", "ref_column": "id"},
        {"table": "reviews", "column": "product_id", "ref_table": "products", "ref_column": "id"},
        {"table": "reviews", "column": "customer_id", "ref_table": "customers", "ref_column": "id"},
    ]
    return tables, foreign_keys


def test_link_schema_pulls_bridge_tables_and_excludes_hr_domain() -> None:
    tables, foreign_keys = _combined_11_table_schema()
    question = "What is the total revenue generated by each supplier country, excluding cancelled orders?"

    linked_tables, linked_fks = link_schema(question, tables, foreign_keys)
    linked_names = [tbl["name"] for tbl in linked_tables]

    assert linked_names == ["suppliers", "products", "orders", "order_items"]
    for hr_table in ("departments", "employees", "sales"):
        assert hr_table not in linked_names

    ddl = format_schema_ddl(linked_tables, linked_fks)
    assert "FOREIGN KEY (supplier_id) REFERENCES suppliers(id)" in ddl
    assert "FOREIGN KEY (order_id) REFERENCES orders(id)" in ddl
    assert "FOREIGN KEY (product_id) REFERENCES products(id)" in ddl
    assert "PRIMARY KEY" in ddl
    assert "category_id integer NOT NULL" in ddl
    assert "REFERENCES categories" not in ddl


def test_link_schema_preserves_self_referencing_fk_in_ddl() -> None:
    tables, foreign_keys = _combined_11_table_schema()
    linked_tables, linked_fks = link_schema(
        "List all categories and their parent categories",
        tables,
        foreign_keys,
    )

    assert [tbl["name"] for tbl in linked_tables] == ["categories"]
    assert linked_fks == [
        {"table": "categories", "column": "parent_category_id", "ref_table": "categories", "ref_column": "id"}
    ]
    ddl = format_schema_ddl(linked_tables, linked_fks)
    assert "FOREIGN KEY (parent_category_id) REFERENCES categories(id)" in ddl


def test_link_schema_falls_back_to_all_tables_when_no_tokens_match() -> None:
    tables, foreign_keys = _combined_11_table_schema()
    linked_tables, linked_fks = link_schema("xyzzy qwerty foo", tables, foreign_keys)

    assert len(linked_tables) == len(tables)
    assert len(linked_fks) == len(foreign_keys)


def test_format_join_paths_and_find_column_owners() -> None:
    tables, foreign_keys = _combined_11_table_schema()

    assert format_join_paths([]) == ""
    join_text = format_join_paths(
        [{"table": "products", "column": "supplier_id", "ref_table": "suppliers", "ref_column": "id"}]
    )
    assert join_text == "JOIN PATHS:\n- products.supplier_id = suppliers.id"

    ddl = format_schema_ddl(tables[:2], foreign_keys[:1])
    assert "JOIN PATHS:\n- employees.department_id = departments.id" in ddl

    assert find_column_owners("COUNTRY", tables) == ["suppliers", "customers"]
    assert find_column_owners("unit_price", tables) == ["products", "order_items"]
    assert find_column_owners("nonexistent", tables) == []
