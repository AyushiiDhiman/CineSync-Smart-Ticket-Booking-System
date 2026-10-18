

CREATE DATABASE IF NOT EXISTS cinesync;
USE cinesync;

CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(150) NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE theatres (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    location VARCHAR(200)
);

CREATE TABLE movies (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    duration_min INT
);

CREATE TABLE shows (
    id INT AUTO_INCREMENT PRIMARY KEY,
    movie_id INT NOT NULL,
    theatre_id INT NOT NULL,
    show_time DATETIME NOT NULL,
    FOREIGN KEY (movie_id) REFERENCES movies(id),
    FOREIGN KEY (theatre_id) REFERENCES theatres(id)
);


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

CREATE TABLE bookings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    seat_id INT NOT NULL,
    state ENUM('pending', 'confirmed', 'cancelled') DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (seat_id) REFERENCES seats(id)
);

CREATE TABLE payments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    booking_id INT NOT NULL,
    amount DECIMAL(8,2) NOT NULL,
    status ENUM('success', 'failed') NOT NULL,
    paid_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (booking_id) REFERENCES bookings(id)
);

-- schema ready for reviews, not wired up yet (phase 3)
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


INSERT INTO theatres (name, location) VALUES ('PVR Cinemas', 'City Mall');


INSERT INTO movies (title, duration_min) VALUES
('Kalki 2898 AD', 180),
('Pathaan', 146),
('Jawan', 169),
('Animal', 201),
('Stree 2', 147);


INSERT INTO shows (movie_id, theatre_id, show_time) VALUES
(1, 1, '2026-10-15 19:00:00'),
(2, 1, '2026-10-15 20:00:00'),
(3, 1, '2026-10-15 18:30:00'),
(4, 1, '2026-10-15 21:00:00'),
(5, 1, '2026-10-15 17:45:00');


INSERT INTO seats (show_id, seat_no, status)
VALUES
-- show 1
(1,'A1','available'),(1,'A2','available'),(1,'A3','available'),(1,'A4','available'),(1,'A5','available'),
(1,'B1','available'),(1,'B2','available'),(1,'B3','available'),(1,'B4','available'),(1,'B5','available'),
(1,'C1','available'),(1,'C2','available'),(1,'C3','available'),(1,'C4','available'),(1,'C5','available'),
(1,'D1','available'),(1,'D2','available'),(1,'D3','available'),(1,'D4','available'),(1,'D5','available'),
-- show 2
(2,'A1','available'),(2,'A2','available'),(2,'A3','available'),(2,'A4','available'),(2,'A5','available'),
(2,'B1','available'),(2,'B2','available'),(2,'B3','available'),(2,'B4','available'),(2,'B5','available'),
(2,'C1','available'),(2,'C2','available'),(2,'C3','available'),(2,'C4','available'),(2,'C5','available'),
(2,'D1','available'),(2,'D2','available'),(2,'D3','available'),(2,'D4','available'),(2,'D5','available'),
-- show 3
(3,'A1','available'),(3,'A2','available'),(3,'A3','available'),(3,'A4','available'),(3,'A5','available'),
(3,'B1','available'),(3,'B2','available'),(3,'B3','available'),(3,'B4','available'),(3,'B5','available'),
(3,'C1','available'),(3,'C2','available'),(3,'C3','available'),(3,'C4','available'),(3,'C5','available'),
(3,'D1','available'),(3,'D2','available'),(3,'D3','available'),(3,'D4','available'),(3,'D5','available'),
-- show 4
(4,'A1','available'),(4,'A2','available'),(4,'A3','available'),(4,'A4','available'),(4,'A5','available'),
(4,'B1','available'),(4,'B2','available'),(4,'B3','available'),(4,'B4','available'),(4,'B5','available'),
(4,'C1','available'),(4,'C2','available'),(4,'C3','available'),(4,'C4','available'),(4,'C5','available'),
(4,'D1','available'),(4,'D2','available'),(4,'D3','available'),(4,'D4','available'),(4,'D5','available'),
-- show 5
(5,'A1','available'),(5,'A2','available'),(5,'A3','available'),(5,'A4','available'),(5,'A5','available'),
(5,'B1','available'),(5,'B2','available'),(5,'B3','available'),(5,'B4','available'),(5,'B5','available'),
(5,'C1','available'),(5,'C2','available'),(5,'C3','available'),(5,'C4','available'),(5,'C5','available'),
(5,'D1','available'),(5,'D2','available'),(5,'D3','available'),(5,'D4','available'),(5,'D5','available');

INSERT INTO users (name, email) VALUES ('Test User A', 'usera@test.com'), ('Test User B', 'userb@test.com');

INSERT INTO food_items (name, price) VALUES
('Popcorn (Large)', 220.00),
('Popcorn (Medium)', 160.00),
('Coke (500ml)', 90.00),
('Nachos with Cheese', 180.00),
('Combo: Popcorn + Coke', 280.00);


CREATE OR REPLACE VIEW available_seats_per_show AS
SELECT
    sh.id AS show_id,
    m.title AS movie_title,
    sh.show_time,
    COUNT(s.id) AS available_seats
FROM shows sh
JOIN movies m ON sh.movie_id = m.id
JOIN seats s ON s.show_id = sh.id AND s.status = 'available'
GROUP BY sh.id, m.title, sh.show_time;


CREATE TABLE IF NOT EXISTS seat_audit_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    seat_id INT NOT NULL,
    old_status VARCHAR(20),
    new_status VARCHAR(20),
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


DROP TRIGGER IF EXISTS seat_status_change;

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

DROP PROCEDURE IF EXISTS ConfirmBooking;

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
