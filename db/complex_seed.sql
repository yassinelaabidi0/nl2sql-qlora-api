DROP TABLE IF EXISTS reviews, shipments, order_items, orders, customers, products, suppliers, categories CASCADE;

CREATE TABLE categories (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    parent_category_id INTEGER REFERENCES categories(id)
);

CREATE TABLE suppliers (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    country TEXT NOT NULL,
    reliability_score NUMERIC(3,2) NOT NULL
);

CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    sku TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    unit_price NUMERIC(10,2) NOT NULL,
    cost_price NUMERIC(10,2) NOT NULL,
    stock_qty INTEGER NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE customers (
    id SERIAL PRIMARY KEY,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    country TEXT NOT NULL,
    tier TEXT NOT NULL,
    signup_date DATE NOT NULL
);

CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    order_date TIMESTAMP NOT NULL,
    status TEXT NOT NULL,
    shipping_cost NUMERIC(8,2) NOT NULL,
    discount_pct NUMERIC(5,2) NOT NULL DEFAULT 0
);

CREATE TABLE order_items (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL,
    unit_price NUMERIC(10,2) NOT NULL
);

CREATE TABLE shipments (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    carrier TEXT NOT NULL,
    warehouse TEXT NOT NULL,
    shipped_at TIMESTAMP NOT NULL,
    delivered_at TIMESTAMP,
    delivery_status TEXT NOT NULL
);

CREATE TABLE reviews (
    id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id),
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    created_at DATE NOT NULL
);

INSERT INTO categories (id, name, parent_category_id) VALUES
(1, 'Electronics', NULL),
(2, 'Laptops', 1),
(3, 'Audio', 1),
(4, 'Home Office', NULL),
(5, 'Furniture', 4),
(6, 'Accessories', 1);

INSERT INTO suppliers (id, name, country, reliability_score) VALUES
(1, 'NordicTech', 'Sweden', 4.85),
(2, 'ShenzhenCore', 'China', 4.30),
(3, 'EuroCraft', 'Germany', 4.65),
(4, 'AtlasAudio', 'Japan', 4.92);

INSERT INTO products (id, sku, name, category_id, supplier_id, unit_price, cost_price, stock_qty, is_active) VALUES
(1, 'LAP-101', 'ProBook 14', 2, 1, 1450.00, 920.00, 35, TRUE),
(2, 'LAP-102', 'UltraSlim 16', 2, 2, 1890.00, 1250.00, 18, TRUE),
(3, 'AUD-201', 'Studio ANC Headphones', 3, 4, 340.00, 155.00, 90, TRUE),
(4, 'AUD-202', 'Pulse Earbuds Pro', 3, 4, 195.00, 82.00, 140, TRUE),
(5, 'FRN-301', 'ErgoMesh Chair', 5, 3, 620.00, 340.00, 24, TRUE),
(6, 'FRN-302', 'Standing Desk Oak', 5, 3, 780.00, 460.00, 12, TRUE),
(7, 'ACC-401', 'Thunderbolt Dock', 6, 2, 210.00, 95.00, 65, TRUE),
(8, 'ACC-402', 'Mechanical Numpad', 6, 1, 85.00, 38.00, 50, FALSE);

INSERT INTO customers (id, full_name, email, country, tier, signup_date) VALUES
(1, 'Amine Ben Salem', 'amine@example.com', 'Tunisia', 'Enterprise', '2024-02-14'),
(2, 'Claire Moreau', 'claire@example.com', 'France', 'Enterprise', '2024-05-03'),
(3, 'Lukas Weber', 'lukas@example.com', 'Germany', 'Pro', '2024-08-19'),
(4, 'Sofia Rossi', 'sofia@example.com', 'Italy', 'Pro', '2025-01-11'),
(5, 'Youssef Trabelsi', 'youssef@example.com', 'Tunisia', 'Standard', '2025-03-22'),
(6, 'Hannah Lindqvist', 'hannah@example.com', 'Sweden', 'Enterprise', '2025-06-08'),
(7, 'Mateo Silva', 'mateo@example.com', 'Spain', 'Standard', '2025-09-17'),
(8, 'Nadia Mansour', 'nadia@example.com', 'France', 'Standard', '2026-01-05');

INSERT INTO orders (id, customer_id, order_date, status, shipping_cost, discount_pct) VALUES
(1, 1, '2026-08-02 10:15:00', 'delivered', 25.00, 10.00),
(2, 2, '2026-08-05 14:40:00', 'delivered', 30.00, 5.00),
(3, 3, '2026-08-12 09:05:00', 'delivered', 20.00, 0.00),
(4, 1, '2026-09-01 16:20:00', 'delivered', 0.00, 15.00),
(5, 4, '2026-09-10 11:30:00', 'cancelled', 15.00, 0.00),
(6, 5, '2026-09-18 18:45:00', 'delivered', 18.00, 0.00),
(7, 6, '2026-10-04 08:50:00', 'delivered', 0.00, 12.00),
(8, 2, '2026-10-19 13:10:00', 'shipped', 25.00, 5.00),
(9, 7, '2026-11-02 15:00:00', 'delivered', 15.00, 0.00),
(10, 6, '2026-11-18 10:25:00', 'shipped', 0.00, 10.00);

INSERT INTO order_items (id, order_id, product_id, quantity, unit_price) VALUES
(1, 1, 1, 2, 1450.00),
(2, 1, 3, 2, 340.00),
(3, 2, 2, 1, 1890.00),
(4, 2, 5, 2, 620.00),
(5, 3, 4, 3, 195.00),
(6, 3, 7, 1, 210.00),
(7, 4, 6, 3, 780.00),
(8, 4, 5, 3, 620.00),
(9, 5, 2, 1, 1890.00),
(10, 6, 4, 2, 195.00),
(11, 7, 1, 4, 1450.00),
(12, 7, 7, 4, 210.00),
(13, 8, 3, 2, 340.00),
(14, 9, 5, 1, 620.00),
(15, 10, 2, 2, 1890.00),
(16, 10, 6, 1, 780.00);

INSERT INTO shipments (id, order_id, carrier, warehouse, shipped_at, delivered_at, delivery_status) VALUES
(1, 1, 'DHL', 'Frankfurt', '2026-08-03 08:00:00', '2026-08-06 14:30:00', 'delivered'),
(2, 2, 'UPS', 'Paris', '2026-08-06 09:00:00', '2026-08-08 11:15:00', 'delivered'),
(3, 3, 'DHL', 'Frankfurt', '2026-08-13 07:30:00', '2026-08-15 16:00:00', 'delivered'),
(4, 4, 'FedEx', 'Paris', '2026-09-02 10:00:00', '2026-09-08 17:45:00', 'delayed'),
(5, 6, 'DHL', 'Frankfurt', '2026-09-19 12:00:00', '2026-09-23 10:20:00', 'delivered'),
(6, 7, 'UPS', 'Stockholm', '2026-10-05 07:00:00', '2026-10-07 13:00:00', 'delivered'),
(7, 8, 'FedEx', 'Paris', '2026-10-20 11:00:00', NULL, 'in_transit'),
(8, 9, 'UPS', 'Madrid', '2026-11-03 09:30:00', '2026-11-05 15:40:00', 'delivered'),
(9, 10, 'DHL', 'Stockholm', '2026-11-19 08:15:00', NULL, 'in_transit');

INSERT INTO reviews (id, product_id, customer_id, rating, created_at) VALUES
(1, 1, 1, 5, '2026-08-10'),
(2, 3, 1, 4, '2026-08-12'),
(3, 2, 2, 5, '2026-08-14'),
(4, 5, 2, 4, '2026-08-15'),
(5, 4, 3, 3, '2026-08-20'),
(6, 6, 1, 5, '2026-09-12'),
(7, 4, 5, 4, '2026-09-28'),
(8, 1, 6, 5, '2026-10-12'),
(9, 7, 6, 4, '2026-10-13'),
(10, 5, 7, 2, '2026-11-10');

GRANT SELECT ON ALL TABLES IN SCHEMA public TO nl2sql_ro;
REVOKE ALL ON TABLE query_logs FROM nl2sql_ro;
