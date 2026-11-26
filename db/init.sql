-- Least-privilege PostgreSQL schema, seed data, and role isolation.

CREATE TABLE IF NOT EXISTS departments (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    budget NUMERIC(12, 2) NOT NULL
);

CREATE TABLE IF NOT EXISTS employees (
    id SERIAL PRIMARY KEY,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL,
    department_id INTEGER NOT NULL REFERENCES departments(id),
    salary NUMERIC(10, 2) NOT NULL,
    hired_at DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS sales (
    id SERIAL PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    region TEXT NOT NULL,
    quarter TEXT NOT NULL,
    amount NUMERIC(12, 2) NOT NULL
);

CREATE TABLE IF NOT EXISTS query_logs (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    question TEXT NOT NULL,
    generated_sql TEXT NOT NULL,
    status TEXT NOT NULL,
    latency_ms DOUBLE PRECISION NOT NULL,
    error_message TEXT
);

INSERT INTO departments (id, name, budget) VALUES
    (1, 'Engineering', 1200000.00),
    (2, 'Sales', 850000.00),
    (3, 'Product', 640000.00),
    (4, 'Finance', 420000.00)
ON CONFLICT (id) DO NOTHING;

INSERT INTO employees (id, full_name, role, department_id, salary, hired_at) VALUES
    (1, 'Alice Chen', 'Staff Engineer', 1, 165000.00, '2022-03-14'),
    (2, 'Marcus Vance', 'ML Engineer', 1, 152000.00, '2023-01-09'),
    (3, 'Priya Nair', 'Enterprise AE', 2, 134000.00, '2021-11-01'),
    (4, 'Daniel Ortiz', 'Account Manager', 2, 118000.00, '2024-02-19'),
    (5, 'Hannah Brooks', 'Product Lead', 3, 148000.00, '2022-08-22'),
    (6, 'Kenji Sato', 'Financial Analyst', 4, 112000.00, '2023-06-12')
ON CONFLICT (id) DO NOTHING;

INSERT INTO sales (id, employee_id, region, quarter, amount) VALUES
    (1, 3, 'North America', '2025-Q1', 210000.00),
    (2, 3, 'North America', '2025-Q2', 245000.00),
    (3, 4, 'EMEA', '2025-Q1', 142000.00),
    (4, 4, 'EMEA', '2025-Q2', 168000.00),
    (5, 3, 'APAC', '2025-Q3', 195000.00),
    (6, 4, 'LATAM', '2025-Q3', 98000.00)
ON CONFLICT (id) DO NOTHING;

SELECT setval('departments_id_seq', COALESCE((SELECT MAX(id) FROM departments), 1));
SELECT setval('employees_id_seq', COALESCE((SELECT MAX(id) FROM employees), 1));
SELECT setval('sales_id_seq', COALESCE((SELECT MAX(id) FROM sales), 1));

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nl2sql_ro') THEN
        CREATE ROLE nl2sql_ro LOGIN PASSWORD 'nl2sql_ro';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nl2sql_logger') THEN
        CREATE ROLE nl2sql_logger LOGIN PASSWORD 'nl2sql_logger';
    END IF;
END $$;

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO nl2sql_ro, nl2sql_logger;

-- Read-only query role: SELECT only on business tables, zero access to query_logs, 3s statement timeout.
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM nl2sql_ro;
GRANT SELECT ON TABLE departments, employees, sales TO nl2sql_ro;
REVOKE ALL ON TABLE query_logs FROM nl2sql_ro;
ALTER ROLE nl2sql_ro SET statement_timeout = '3000ms';

-- Audit logger role: SELECT/INSERT only on query_logs + sequence usage, zero access to business tables.
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM nl2sql_logger;
GRANT SELECT, INSERT ON TABLE query_logs TO nl2sql_logger;
GRANT USAGE, SELECT ON SEQUENCE query_logs_id_seq TO nl2sql_logger;
