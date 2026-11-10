"""
Generates upcoming shows (and their seats) for every theatre/movie.

Why this exists: Phase 3 hard-coded show dates in schema.sql, so a few
days later every show was in the past. This script creates shows
relative to TODAY, and is safe to run again any time - it only inserts
what's missing.

    python seed_shows.py          # next 3 days
    python seed_shows.py 5        # next 5 days
"""

import sys
from datetime import datetime, timedelta

from database import get_connection

SLOTS = ["10:30", "14:00", "17:30", "21:00"]   # 4 possible slots a day
SLOTS_PER_MOVIE = 3                            # each movie gets 3 of them
ROWS = "ABCDEF"
COLS = 8


def slots_for(theatre_id, movie_id):
    # rotate which 3 of the 4 slots a movie gets, so theatres don't
    # all look identical
    start = (theatre_id + movie_id) % len(SLOTS)
    return [SLOTS[(start + i) % len(SLOTS)] for i in range(SLOTS_PER_MOVIE)]


def base_price(theatre_id, movie_id):
    return 180 + 20 * ((theatre_id * 3 + movie_id) % 5)   # Rs.180 - Rs.260


def seed_upcoming_shows(conn, days=3, theatre_ids=None):
    cur = conn.cursor()
    cur.execute("SELECT id FROM theatres")
    theatres = [r[0] for r in cur.fetchall()]
    if theatre_ids is not None:
        theatres = [t for t in theatres if t in set(theatre_ids)]
    cur.execute("SELECT id FROM movies")
    movies = [r[0] for r in cur.fetchall()]

    cur.execute("SELECT movie_id, theatre_id, show_time FROM shows")
    existing = {(m, t, st) for m, t, st in cur.fetchall()}

    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    new_shows = 0

    for d in range(days):
        day = today + timedelta(days=d)
        for t in theatres:
            for m in movies:
                for slot in slots_for(t, m):
                    h, mi = map(int, slot.split(":"))
                    st = day.replace(hour=h, minute=mi)
                    if st < now or (m, t, st) in existing:
                        continue
                    cur.execute(
                        "INSERT INTO shows (movie_id, theatre_id, show_time, price) VALUES (%s,%s,%s,%s)",
                        (m, t, st, base_price(t, m)),
                    )
                    new_shows += 1

    # seats for any show that doesn't have them yet
    cur.execute(
        "SELECT sh.id FROM shows sh LEFT JOIN seats s ON s.show_id = sh.id "
        "WHERE s.id IS NULL"
    )
    empty = [r[0] for r in cur.fetchall()]
    seat_rows = [(sid, f"{r}{c}") for sid in empty for r in ROWS for c in range(1, COLS + 1)]
    if seat_rows:
        cur.executemany(
            "INSERT INTO seats (show_id, seat_no, status) VALUES (%s,%s,'available')",
            seat_rows,
        )
    conn.commit()
    cur.close()
    return new_shows, len(empty)


if __name__ == "__main__":
    n_days = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    conn = get_connection()
    shows, with_seats = seed_upcoming_shows(conn, n_days)
    conn.close()
    print(f"Created {shows} new show(s); added seats to {with_seats} show(s).")
