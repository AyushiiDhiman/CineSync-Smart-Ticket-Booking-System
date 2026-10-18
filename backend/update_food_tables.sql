-- Run this ONLY if you already ran schema.sql before and don't want to
-- drop everything. This just adds the food ordering tables.
-- Run with: source update_food_tables.sql;  (after USE cinesync;)

USE cinesync;

CREATE TABLE IF NOT EXISTS food_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    price DECIMAL(6,2) NOT NULL
);

CREATE TABLE IF NOT EXISTS food_orders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    booking_id INT NOT NULL,
    food_item_id INT NOT NULL,
    quantity INT NOT NULL DEFAULT 1,
    FOREIGN KEY (booking_id) REFERENCES bookings(id),
    FOREIGN KEY (food_item_id) REFERENCES food_items(id)
);

INSERT INTO food_items (name, price)
SELECT * FROM (SELECT 'Popcorn (Large)' AS name, 220.00 AS price) AS tmp
WHERE NOT EXISTS (SELECT 1 FROM food_items WHERE name = 'Popcorn (Large)');

INSERT INTO food_items (name, price)
SELECT * FROM (SELECT 'Popcorn (Medium)', 160.00) AS tmp
WHERE NOT EXISTS (SELECT 1 FROM food_items WHERE name = 'Popcorn (Medium)');

INSERT INTO food_items (name, price)
SELECT * FROM (SELECT 'Coke (500ml)', 90.00) AS tmp
WHERE NOT EXISTS (SELECT 1 FROM food_items WHERE name = 'Coke (500ml)');

INSERT INTO food_items (name, price)
SELECT * FROM (SELECT 'Nachos with Cheese', 180.00) AS tmp
WHERE NOT EXISTS (SELECT 1 FROM food_items WHERE name = 'Nachos with Cheese');

INSERT INTO food_items (name, price)
SELECT * FROM (SELECT 'Combo: Popcorn + Coke', 280.00) AS tmp
WHERE NOT EXISTS (SELECT 1 FROM food_items WHERE name = 'Combo: Popcorn + Coke');
