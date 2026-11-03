"""
Upgrades an existing Phase 3 database to Phase 4 WITHOUT losing bookings.

Adds: theatres.city/lat/lng/amenities, movies.genre/language, shows.price,
the extra demo theatres, and fresh upcoming shows + seats.

Safe to run more than once - every step checks before it changes anything.

    python migrate_to_phase4.py
"""

from database import get_connection
from seed_shows import seed_upcoming_shows


def column_exists(cur, table, column):
    cur.execute(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = %s AND column_name = %s",
        (table, column),
    )
    return cur.fetchone()[0] > 0


def add_column(cur, table, column, ddl):
    if column_exists(cur, table, column):
        print(f"  = {table}.{column} already exists")
    else:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        print(f"  + added {table}.{column}")


# name -> (location, city, lat, lng, amenities). DEMO data - replace with real venues.
THEATRES = [
    ("PVR Cinemas",         "City Mall, Rajpur Road",      "Dehradun",  30.335800, 78.052900, "Dolby Atmos,Recliners,Food Court,Parking"),
    ("INOX",                "Downtown Plaza, Race Course", "Dehradun",  30.312000, 78.034500, "4K Laser,Food Court,Parking"),
    ("Cinepolis",           "Mall Road",                   "Dehradun",  30.304000, 78.015000, "Dolby Atmos,Wheelchair Access"),
    ("Doon Cineplex",       "Prem Nagar",                  "Dehradun",  30.333000, 77.961000, "Recliners,Parking"),
    ("Capital Screens",     "Connaught Place",             "New Delhi", 28.631500, 77.216700, "Dolby Atmos,4K Laser,Recliners"),
    ("Yamuna Multiplex",    "Laxmi Nagar",                 "New Delhi", 28.630400, 77.277300, "Food Court,Parking"),
    ("Marine Drive Cinemas","Marine Lines",                "Mumbai",    18.944000, 72.823000, "Dolby Atmos,Recliners,Food Court"),
    ("Garden City Cinemas", "MG Road",                     "Bengaluru", 12.975600, 77.606800, "4K Laser,Wheelchair Access,Parking"),
    ("Ganga Talkies",       "Har Ki Pauri Road",           "Haridwar",  29.945700, 78.164200, "Parking,Food Court"),
]

MOVIE_INFO = {
    "Kalki 2898 AD": ("Sci-Fi, Action", "Hindi"),
    "Pathaan":       ("Action, Thriller", "Hindi"),
    "Jawan":         ("Action, Thriller", "Hindi"),
    "Animal":        ("Crime, Drama", "Hindi"),
    "Stree 2":       ("Horror, Comedy", "Hindi"),
}


def main():
    conn = get_connection()
    cur = conn.cursor()

    print("Columns:")
    add_column(cur, "theatres", "city", "VARCHAR(100) DEFAULT NULL")
    add_column(cur, "theatres", "lat", "DECIMAL(9,6) DEFAULT NULL")
    add_column(cur, "theatres", "lng", "DECIMAL(9,6) DEFAULT NULL")
    add_column(cur, "theatres", "amenities", "VARCHAR(200) DEFAULT NULL")
    add_column(cur, "movies", "genre", "VARCHAR(100) DEFAULT NULL")
    add_column(cur, "movies", "language", "VARCHAR(50) DEFAULT NULL")
    add_column(cur, "shows", "price", "DECIMAL(6,2) NOT NULL DEFAULT 250.00")
    conn.commit()

    print("Theatres:")
    for name, loc, city, lat, lng, amen in THEATRES:
        cur.execute("SELECT id FROM theatres WHERE name = %s", (name,))
        row = cur.fetchone()
        if row:
            cur.execute(
                "UPDATE theatres SET location=%s, city=%s, lat=%s, lng=%s, amenities=%s WHERE id=%s",
                (loc, city, lat, lng, amen, row[0]),
            )
            print(f"  ~ updated {name}")
        else:
            cur.execute(
                "INSERT INTO theatres (name, location, city, lat, lng, amenities) VALUES (%s,%s,%s,%s,%s,%s)",
                (name, loc, city, lat, lng, amen),
            )
            print(f"  + inserted {name}")

    print("Movies:")
    for title, (genre, lang) in MOVIE_INFO.items():
        cur.execute("UPDATE movies SET genre=%s, language=%s WHERE title=%s", (genre, lang, title))
    conn.commit()

    print("Shows:")
    shows, with_seats = seed_upcoming_shows(conn, days=3)
    print(f"  + {shows} new show(s), seats added to {with_seats} show(s)")

    cur.close()
    conn.close()
    print("Done. Phase 4 ready - restart app.py.")


if __name__ == "__main__":
    main()
