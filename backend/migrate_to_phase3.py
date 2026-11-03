"""
Run this ONCE if your database already has the Phase 2 setup (single
theatre, mock payment only) and you don't want to drop everything and
lose your existing bookings.

Adds: 2 more theatres (INOX, Cinepolis) with a show + 20 seats for
every existing movie at each, the payment_orders table, two new
columns (bookings.group_order_id, payments.razorpay_payment_id), and
the view/trigger/stored procedure if they aren't already there.

Everything here checks first, so it's safe to run more than once by
accident - it just skips whatever already exists.

Bonus: doing this through Python instead of the mysql command line
means we don't need the DELIMITER // trick at all for the trigger and
procedure - mysql-connector sends the whole CREATE TRIGGER / CREATE
PROCEDURE block as one statement regardless of the semicolons inside
it, so none of the "ERROR 1046 no database selected" / DELIMITER
confusion that happens in the CLI comes up here.

Run with: python migrate_to_phase3.py
"""

from database import get_connection

NEW_THEATRES = [
    ("INOX", "Downtown Plaza"),
    ("Cinepolis", "Mall Road"),
]

SEAT_NUMBERS = [f"{row}{num}" for row in "ABCD" for num in range(1, 6)]


def add_theatres_and_shows(cursor, conn):
    cursor.execute("SELECT id, title FROM movies")
    movies = cursor.fetchall()

    for name, location in NEW_THEATRES:
        cursor.execute("SELECT id FROM theatres WHERE name = %s", (name,))
        existing = cursor.fetchone()

        if existing:
            theatre_id = existing["id"]
            print(f"'{name}' already exists, using it.")
        else:
            cursor.execute(
                "INSERT INTO theatres (name, location) VALUES (%s, %s)",
                (name, location)
            )
            theatre_id = cursor.lastrowid
            conn.commit()
            print(f"Added theatre '{name}'.")

        for movie in movies:
            cursor.execute(
                "SELECT id FROM shows WHERE movie_id = %s AND theatre_id = %s",
                (movie["id"], theatre_id)
            )
            if cursor.fetchone():
                continue  # this movie already has a show at this theatre

            cursor.execute(
                "INSERT INTO shows (movie_id, theatre_id, show_time) "
                "VALUES (%s, %s, '2026-10-20 19:00:00')",
                (movie["id"], theatre_id)
            )
            show_id = cursor.lastrowid

            for seat_no in SEAT_NUMBERS:
                cursor.execute(
                    "INSERT INTO seats (show_id, seat_no, status) VALUES (%s, %s, 'available')",
                    (show_id, seat_no)
                )

            conn.commit()
            print(f"  added show for '{movie['title']}' at '{name}' (show #{show_id})")


def add_payment_orders_table(cursor, conn):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS payment_orders (
            id INT AUTO_INCREMENT PRIMARY KEY,
            razorpay_order_id VARCHAR(100) NOT NULL UNIQUE,
            user_id INT NOT NULL,
            seat_ids VARCHAR(200) NOT NULL,
            amount DECIMAL(8,2) NOT NULL,
            status ENUM('created', 'paid', 'failed') DEFAULT 'created',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.commit()
    print("payment_orders table is ready.")


def add_column_if_missing(cursor, conn, table, column, definition):
    cursor.execute("""
        SELECT COUNT(*) AS cnt FROM information_schema.columns
        WHERE table_schema = DATABASE() AND table_name = %s AND column_name = %s
    """, (table, column))
    if cursor.fetchone()["cnt"] > 0:
        print(f"{table}.{column} already exists, skipping.")
        return

    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    conn.commit()
    print(f"Added column {table}.{column}")


def add_view(cursor, conn):
    cursor.execute("""
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
        GROUP BY sh.id, m.title, t.name, sh.show_time
    """)
    conn.commit()
    print("View 'available_seats_per_show' is ready.")


def add_trigger(cursor, conn):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS seat_audit_log (
            id INT AUTO_INCREMENT PRIMARY KEY,
            seat_id INT NOT NULL,
            old_status VARCHAR(20),
            new_status VARCHAR(20),
            changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    cursor.execute("DROP TRIGGER IF EXISTS seat_status_change")
    cursor.execute("""
        CREATE TRIGGER seat_status_change
        AFTER UPDATE ON seats
        FOR EACH ROW
        BEGIN
            IF OLD.status <> NEW.status THEN
                INSERT INTO seat_audit_log (seat_id, old_status, new_status)
                VALUES (NEW.id, OLD.status, NEW.status);
            END IF;
        END
    """)
    conn.commit()
    print("Trigger 'seat_status_change' is ready.")


def add_stored_procedure(cursor, conn):
    cursor.execute("DROP PROCEDURE IF EXISTS ConfirmBooking")
    cursor.execute("""
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
        END
    """)
    conn.commit()
    print("Stored procedure 'ConfirmBooking' is ready.")


def migrate():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        print("--- Theatres & shows ---")
        add_theatres_and_shows(cursor, conn)

        print("\n--- payment_orders table ---")
        add_payment_orders_table(cursor, conn)

        print("\n--- New columns ---")
        add_column_if_missing(cursor, conn, "bookings", "group_order_id", "INT DEFAULT NULL")
        add_column_if_missing(cursor, conn, "payments", "razorpay_payment_id", "VARCHAR(100) DEFAULT NULL")

        print("\n--- View / Trigger / Procedure ---")
        add_view(cursor, conn)
        add_trigger(cursor, conn)
        add_stored_procedure(cursor, conn)

        print("\nMigration complete. Your database is now Phase 3 ready.")

    except Exception as e:
        conn.rollback()
        print(f"Migration error: {e}")
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    migrate()
