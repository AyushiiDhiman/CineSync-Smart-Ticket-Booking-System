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
END 
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

