from database import get_connection

NEW_MOVIES = [
    ("Final Destination", 146, "2026-10-15 20:00:00"),
    ("Interstellar", 169, "2026-10-15 18:30:00"),
    ("Spider-Man: Brand New Day", 201, "2026-10-15 21:00:00"),
    ("Toy Story", 147, "2026-10-15 17:45:00"),
]

SEAT_NUMBERS = [f"{row}{num}" for row in "ABCD" for num in range(1, 6)]


def seed():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("SELECT id FROM theatres LIMIT 1")
        theatre = cursor.fetchone()
        if theatre is None:
            print("No theatre found - run schema.sql first.")
            return
        theatre_id = theatre["id"]

        for title, duration, show_time in NEW_MOVIES:
            cursor.execute("SELECT id FROM movies WHERE title = %s", (title,))
            existing = cursor.fetchone()

            if existing:
                print(f"'{title}' already exists, skipping.")
                continue

            cursor.execute(
                "INSERT INTO movies (title, duration_min) VALUES (%s, %s)",
                (title, duration)
            )
            movie_id = cursor.lastrowid

            cursor.execute(
                "INSERT INTO shows (movie_id, theatre_id, show_time) VALUES (%s, %s, %s)",
                (movie_id, theatre_id, show_time)
            )
            show_id = cursor.lastrowid

            for seat_no in SEAT_NUMBERS:
                cursor.execute(
                    "INSERT INTO seats (show_id, seat_no, status) VALUES (%s, %s, 'available')",
                    (show_id, seat_no)
                )

            conn.commit()
            print(f"Added '{title}' with show #{show_id} and {len(SEAT_NUMBERS)} seats.")

    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    seed()
