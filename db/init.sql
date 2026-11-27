-- Clean reset of domain tables (preserves query_logs)
DROP TABLE IF EXISTS reviews, shipments, payments, order_items, orders, products, suppliers, categories, addresses, customers CASCADE;

-- 1. Customers
CREATE TABLE customers (
    id SERIAL PRIMARY KEY,
    full_name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    country TEXT NOT NULL,
    tier TEXT NOT NULL CHECK (tier IN ('bronze', 'silver', 'gold')),
    signup_date DATE NOT NULL
);

-- 2. Addresses
CREATE TABLE addresses (
    id SERIAL PRIMARY KEY,
    customer_id INT NOT NULL REFERENCES customers(id),
    city TEXT NOT NULL,
    country TEXT NOT NULL,
    postal_code TEXT NOT NULL,
    is_default BOOLEAN NOT NULL DEFAULT TRUE
);

-- 3. Categories
CREATE TABLE categories (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    parent_category_id INT REFERENCES categories(id)
);

-- 4. Suppliers
CREATE TABLE suppliers (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    country TEXT NOT NULL,
    rating NUMERIC(2,1) NOT NULL
);

-- 5. Products
CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    sku TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    category_id INT NOT NULL REFERENCES categories(id),
    supplier_id INT NOT NULL REFERENCES suppliers(id),
    unit_price NUMERIC(10,2) NOT NULL,
    stock_qty INT NOT NULL
);

-- 6. Orders
CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    customer_id INT NOT NULL REFERENCES customers(id),
    shipping_address_id INT NOT NULL REFERENCES addresses(id),
    order_date DATE NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'shipped', 'delivered', 'cancelled'))
);

-- 7. Order Items
CREATE TABLE order_items (
    id SERIAL PRIMARY KEY,
    order_id INT NOT NULL REFERENCES orders(id),
    product_id INT NOT NULL REFERENCES products(id),
    quantity INT NOT NULL,
    unit_price NUMERIC(10,2) NOT NULL,
    discount_pct NUMERIC(5,2) NOT NULL DEFAULT 0.00
);

-- 8. Payments
CREATE TABLE payments (
    id SERIAL PRIMARY KEY,
    order_id INT NOT NULL REFERENCES orders(id),
    method TEXT NOT NULL CHECK (method IN ('card', 'paypal', 'bank_transfer')),
    amount NUMERIC(10,2) NOT NULL,
    paid_at TIMESTAMP NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('completed', 'refunded', 'failed'))
);

-- 9. Shipments
CREATE TABLE shipments (
    id SERIAL PRIMARY KEY,
    order_id INT NOT NULL REFERENCES orders(id),
    carrier TEXT NOT NULL,
    tracking_code TEXT UNIQUE NOT NULL,
    shipped_at TIMESTAMP,
    delivered_at TIMESTAMP
);

-- 10. Reviews
CREATE TABLE reviews (
    id SERIAL PRIMARY KEY,
    product_id INT NOT NULL REFERENCES products(id),
    customer_id INT NOT NULL REFERENCES customers(id),
    rating INT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment TEXT,
    created_at DATE NOT NULL
);

-- Sample Seed Data
INSERT INTO customers (full_name, email, country, tier, signup_date) VALUES
('Amine Ben Ali', 'amine@example.com', 'Tunisia', 'gold', '2025-02-14'),
('Claire Moreau', 'claire@example.com', 'France', 'gold', '2025-04-03'),
('Lukas Weber', 'lukas@example.com', 'Germany', 'silver', '2025-06-19'),
('Sara Mansour', 'sara@example.com', 'Tunisia', 'bronze', '2025-09-01'),
('Kenji Takahashi', 'kenji@example.com', 'Japan', 'silver', '2025-11-12');

INSERT INTO addresses (customer_id, city, country, postal_code, is_default) VALUES
(1, 'Tunis', 'Tunisia', '1002', TRUE),
(2, 'Lyon', 'France', '69001', TRUE),
(3, 'Munich', 'Germany', '80331', TRUE),
(4, 'Sousse', 'Tunisia', '4000', TRUE),
(5, 'Tokyo', 'Japan', '100-0001', TRUE);

INSERT INTO categories (name, parent_category_id) VALUES
('Electronics', NULL),
('Laptops', 1),
('Audio', 1),
('Home Office', NULL),
('Ergonomic Chairs', 4);

INSERT INTO suppliers (name, country, rating) VALUES
('NordicTech AB', 'Sweden', 4.8),
('NipponSound Corp', 'Japan', 4.9),
('RheinWork GmbH', 'Germany', 4.6),
('MedinaHardware SARL', 'Tunisia', 4.5);

INSERT INTO products (sku, name, category_id, supplier_id, unit_price, stock_qty) VALUES
('LAP-101', 'ProBook 15 Ultrabook', 2, 1, 1250.00, 18),
('AUD-202', 'Studio ANC Headphones', 3, 2, 280.00, 45),
('CHR-303', 'AeroMesh Task Chair', 5, 3, 490.00, 12),
('ELE-404', 'USB-C Thunderbolt Dock', 1, 1, 190.00, 30),
('OFF-505', 'Dual Monitor Riser', 4, 4, 95.00, 50);

INSERT INTO orders (customer_id, shipping_address_id, order_date, status) VALUES
(1, 1, '2026-01-10', 'delivered'),
(2, 2, '2026-01-18', 'delivered'),
(3, 3, '2026-02-04', 'shipped'),
(4, 4, '2026-02-15', 'cancelled'),
(1, 1, '2026-03-02', 'delivered'),
(5, 5, '2026-03-11', 'pending');

INSERT INTO order_items (order_id, product_id, quantity, unit_price, discount_pct) VALUES
(1, 1, 1, 1250.00, 10.00),
(1, 4, 2, 190.00, 0.00),
(2, 2, 2, 280.00, 5.00),
(2, 5, 1, 95.00, 0.00),
(3, 3, 1, 490.00, 0.00),
(4, 2, 1, 280.00, 15.00),
(5, 3, 2, 490.00, 10.00),
(6, 1, 1, 1250.00, 0.00);

INSERT INTO payments (order_id, method, amount, paid_at, status) VALUES
(1, 'card', 1505.00, '2026-01-10 10:15:00', 'completed'),
(2, 'paypal', 627.00, '2026-01-18 14:22:00', 'completed'),
(3, 'bank_transfer', 490.00, '2026-02-04 09:05:00', 'completed'),
(4, 'card', 238.00, '2026-02-15 16:40:00', 'refunded'),
(5, 'card', 882.00, '2026-03-02 11:30:00', 'completed');

INSERT INTO shipments (order_id, carrier, tracking_code, shipped_at, delivered_at) VALUES
(1, 'DHL Express', 'DHL-9001', '2026-01-11 08:00:00', '2026-01-14 15:30:00'),
(2, 'UPS', 'UPS-9002', '2026-01-19 09:30:00', '2026-01-22 12:10:00'),
(3, 'FedEx', 'FDX-9003', '2026-02-05 13:00:00', NULL),
(5, 'DHL Express', 'DHL-9005', '2026-03-03 07:45:00', '2026-03-06 17:00:00');

INSERT INTO reviews (product_id, customer_id, rating, comment, created_at) VALUES
(1, 1, 5, 'Fast build quality and crisp display.', '2026-01-20'),
(2, 2, 4, 'Great noise cancellation, slightly tight fit.', '2026-01-28'),
(3, 1, 5, 'Best chair for long coding sessions.', '2026-03-10'),
(4, 1, 4, 'Works reliably with two 4K monitors.', '2026-01-22');

-- Ensure read-only role can query all 10 tables
GRANT USAGE ON SCHEMA public TO nl2sql_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO nl2sql_ro;