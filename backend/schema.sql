-- CineSync database schema (Phase 4 - full version)
-- Fresh install:  mysql -u root -p < schema.sql   then   python seed_shows.py

CREATE DATABASE IF NOT EXISTS cinesync;
USE cinesync;

CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(150) NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Phase 4: lat/lng + city make "cinemas near me" possible. amenities is a
-- comma-separated list (simple on purpose - one small table fewer to explain).
CREATE TABLE theatres (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    location VARCHAR(200),
    city VARCHAR(100),
    lat DECIMAL(9,6),
    lng DECIMAL(9,6),
    amenities VARCHAR(200) DEFAULT NULL,
    INDEX idx_theatres_city (city)
);

CREATE TABLE movies (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    duration_min INT,
    genre VARCHAR(100) DEFAULT NULL,
    language VARCHAR(50) DEFAULT NULL
);

CREATE TABLE shows (
    id INT AUTO_INCREMENT PRIMARY KEY,
    movie_id INT NOT NULL,
    theatre_id INT NOT NULL,
    show_time DATETIME NOT NULL,
    price DECIMAL(6,2) NOT NULL DEFAULT 250.00,   -- base price; row tier adds on top (see geo.py)
    INDEX idx_shows_theatre_time (theatre_id, show_time),
    FOREIGN KEY (movie_id) REFERENCES movies(id),
    FOREIGN KEY (theatre_id) REFERENCES theatres(id)
);

-- the important one - this is what we lock on
CREATE TABLE seats (
    id INT AUTO_INCREMENT PRIMARY KEY,
    show_id INT NOT NULL,
    seat_no VARCHAR(10) NOT NULL,
    status ENUM('available', 'held', 'booked') DEFAULT 'available',
    held_by INT DEFAULT NULL,
    held_until DATETIME DEFAULT NULL,
    FOREIGN KEY (show_id) REFERENCES shows(id),
    FOREIGN KEY (held_by) REFERENCES users(id)
);

-- tracks a Razorpay order from the moment we create it until payment
-- is verified. seat_ids is a simple comma-separated list (e.g. "12,13,14")
-- rather than a separate join table - a deliberate simplification since
-- an order always maps to one specific set of seats for one booking attempt
CREATE TABLE payment_orders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    razorpay_order_id VARCHAR(100) NOT NULL UNIQUE,
    user_id INT NOT NULL,
    seat_ids VARCHAR(200) NOT NULL,
    amount DECIMAL(8,2) NOT NULL,
    status ENUM('created', 'paid', 'failed') DEFAULT 'created',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- group_order_id links multiple seat bookings together when a family/
-- group books more than one seat in the same transaction - lets "My
-- Bookings" show them as one group instead of N separate entries
CREATE TABLE bookings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    seat_id INT NOT NULL,
    state ENUM('pending', 'confirmed', 'cancelled') DEFAULT 'pending',
    group_order_id INT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (seat_id) REFERENCES seats(id),
    FOREIGN KEY (group_order_id) REFERENCES payment_orders(id)
);

-- razorpay_payment_id stores the actual gateway payment reference once
-- real Razorpay payments are wired in (Phase 3) - NULL for older mock
-- payments from Phase 2
CREATE TABLE payments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    booking_id INT NOT NULL,
    amount DECIMAL(8,2) NOT NULL,
    status ENUM('success', 'failed') NOT NULL,
    razorpay_payment_id VARCHAR(100) DEFAULT NULL,
    paid_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (booking_id) REFERENCES bookings(id)
);

CREATE TABLE food_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    price DECIMAL(6,2) NOT NULL
);

CREATE TABLE food_orders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    booking_id INT NOT NULL,
    food_item_id INT NOT NULL,
    quantity INT NOT NULL DEFAULT 1,
    FOREIGN KEY (booking_id) REFERENCES bookings(id),
    FOREIGN KEY (food_item_id) REFERENCES food_items(id)
);

CREATE TABLE reviews (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    target_type ENUM('movie', 'seat', 'food') NOT NULL,
    target_id INT NOT NULL,
    rating TINYINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- table the trigger further down writes into
CREATE TABLE seat_audit_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    seat_id INT NOT NULL,
    old_status VARCHAR(20),
    new_status VARCHAR(20),
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


-- ====================================================================
-- sample data. NOTE: theatre names/coordinates below are DEMO data
-- (approximate lat/lng) - replace with real venues for a real launch.
-- Shows and seats are NOT inserted here any more: run seed_shows.py so
-- show dates are always relative to today.
-- ====================================================================

INSERT INTO theatres (name, location, city, lat, lng, amenities) VALUES
('PVR Cinemas',        'City Mall, Rajpur Road',  'Dehradun',  30.335800, 78.052900, 'Dolby Atmos,Recliners,Food Court,Parking'),
('INOX',               'Downtown Plaza, Race Course', 'Dehradun', 30.312000, 78.034500, '4K Laser,Food Court,Parking'),
('Cinepolis',          'Mall Road',               'Dehradun',  30.304000, 78.015000, 'Dolby Atmos,Wheelchair Access'),
('Doon Cineplex',      'Prem Nagar',              'Dehradun',  30.333000, 77.961000, 'Recliners,Parking'),
('Capital Screens',    'Connaught Place',         'New Delhi', 28.631500, 77.216700, 'Dolby Atmos,4K Laser,Recliners'),
('Yamuna Multiplex',   'Laxmi Nagar',             'New Delhi', 28.630400, 77.277300, 'Food Court,Parking'),
('Marine Drive Cinemas','Marine Lines',           'Mumbai',    18.944000, 72.823000, 'Dolby Atmos,Recliners,Food Court'),
('Garden City Cinemas','MG Road',                 'Bengaluru', 12.975600, 77.606800, '4K Laser,Wheelchair Access,Parking'),
('Ganga Talkies',      'Har Ki Pauri Road',       'Haridwar',  29.945700, 78.164200, 'Parking,Food Court');

INSERT INTO movies (title, duration_min, genre, language) VALUES
('Kalki 2898 AD', 180, 'Sci-Fi, Action', 'Hindi'),
('Pathaan',       146, 'Action, Thriller', 'Hindi'),
('Jawan',         169, 'Action, Thriller', 'Hindi'),
('Animal',        201, 'Crime, Drama', 'Hindi'),
('Stree 2',       147, 'Horror, Comedy', 'Hindi');

INSERT INTO users (name, email) VALUES
('Test User A', 'usera@test.com'),
('Test User B', 'userb@test.com');

INSERT INTO food_items (name, price) VALUES
('Popcorn (Large)', 220.00),
('Popcorn (Medium)', 160.00),
('Coke (500ml)', 90.00),
('Nachos with Cheese', 180.00),
('Combo: Popcorn + Coke', 280.00);


-- ====================================================================
-- DBMS objects: view, trigger, stored procedure - not all used by
-- app.py directly (noted below), but here so the project covers the
-- classic DBMS objects and not just plain queries from the python side
-- ====================================================================

CREATE OR REPLACE VIEW available_seats_per_show AS
SELECT
    sh.id AS show_id,
    m.title AS movie_title,
    t.name AS theatre_name,
    sh.show_time,
    COUNT(s.id) AS available_seats
FROM shows sh
JOIN movies m ON sh.movie_id = m.id
JOIN theatres t ON sh.theatre_id = t.id
JOIN seats s ON s.show_id = sh.id AND s.status = 'available'
GROUP BY sh.id, m.title, t.name, sh.show_time;

-- TRIGGER: fires on its own whenever a seat's status changes, we
-- never call this from app.py anywhere
DELIMITER //
CREATE TRIGGER seat_status_change
AFTER UPDATE ON seats
FOR EACH ROW
BEGIN
    IF OLD.status <> NEW.status THEN
        INSERT INTO seat_audit_log (seat_id, old_status, new_status)
        VALUES (NEW.id, OLD.status, NEW.status);
    END IF;
END //
DELIMITER ;

-- STORED PROCEDURE: same booking+payment logic as the Flask route,
-- done as a transaction fully inside the database instead. app.py
-- doesn't call this directly (we kept the python version since it's
-- easier to wire up with Razorpay's callback flow) - this is here to
-- show the same logic also works purely at the DB layer.
DELIMITER //
CREATE PROCEDURE ConfirmBooking(
    IN p_seat_id INT,
    IN p_user_id INT,
    IN p_amount DECIMAL(8,2),
    OUT p_result VARCHAR(100)
)
BEGIN
    DECLARE v_status VARCHAR(20);
    DECLARE v_held_by INT;
    DECLARE v_booking_id INT;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        SET p_result = 'error - transaction rolled back';
    END;

    START TRANSACTION;

    SELECT status, held_by INTO v_status, v_held_by
    FROM seats WHERE id = p_seat_id FOR UPDATE;

    IF v_status != 'held' OR v_held_by != p_user_id THEN
        ROLLBACK;
        SET p_result = 'seat is not held by this user';
    ELSE
        INSERT INTO bookings (user_id, seat_id, state)
        VALUES (p_user_id, p_seat_id, 'confirmed');
        SET v_booking_id = LAST_INSERT_ID();

        INSERT INTO payments (booking_id, amount, status)
        VALUES (v_booking_id, p_amount, 'success');

        UPDATE seats SET status = 'booked' WHERE id = p_seat_id;

        COMMIT;
        SET p_result = CONCAT('booking confirmed, id = ', v_booking_id);
    END IF;
END //
DELIMITER ;
