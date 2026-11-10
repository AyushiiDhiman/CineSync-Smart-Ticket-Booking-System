"""
Pulls REAL cinema locations from OpenStreetMap (Overpass API) for any place
in India, saves them in the `theatres` table, and creates demo shows + seats
for the new ones so they can be booked in this project.

What is real: cinema names and coordinates (OpenStreetMap contributors).
What is NOT real: showtimes, prices and seats - those are generated demo data.
OSM coverage of Indian cinemas is incomplete, so some towns will return few
or no results.
"""
import json
import time
import urllib.parse
import urllib.request

from database import get_connection
from geo import haversine_km
from seed_shows import seed_upcoming_shows

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
FETCH_RADIUS_KM = 25      # how far around the searched point we ask OSM
MIN_LOCAL_THEATRES = 3    # fewer than this nearby -> ask OSM
MAX_NEW_PER_FETCH = 15    # keeps each request (and the seeding) small
CACHE_SECONDS = 24 * 3600

_asked = {}               # (lat cell, lng cell) -> time we last asked OSM
_column_ok = False


def _ensure_column(conn):
    """One-time: add an osm_id column so the same cinema is never inserted twice."""
    global _column_ok
    if _column_ok:
        return
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = 'theatres' AND column_name = 'osm_id'"
    )
    if cur.fetchone()[0] == 0:
        cur.execute("ALTER TABLE theatres ADD COLUMN osm_id VARCHAR(32) NULL, "
                    "ADD UNIQUE KEY uq_theatres_osm (osm_id)")
        conn.commit()
    cur.close()
    _column_ok = True


def _query_overpass(lat, lng, radius_km):
    q = (f'[out:json][timeout:20];'
         f'nwr["amenity"="cinema"](around:{int(radius_km * 1000)},{lat},{lng});'
         f'out center tags;')
    body = urllib.parse.urlencode({"data": q}).encode()
    last_err = None
    for url in OVERPASS_URLS:
        try:
            req = urllib.request.Request(
                url, data=body,
                headers={"User-Agent": "CineSync-college-project/1.0"})
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read().decode())
        except Exception as e:            # try the next mirror
            last_err = e
    raise RuntimeError(f"Overpass unavailable: {last_err}")


def parse_elements(data):
    """Overpass JSON -> list of dicts ready for the theatres table."""
    out = []
    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        name = (tags.get("name") or tags.get("name:en") or "").strip()
        if not name:
            continue                       # unnamed cinemas are useless in a UI
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lng = el.get("lon") or (el.get("center") or {}).get("lon")
        if lat is None or lng is None:
            continue
        city = (tags.get("addr:city") or tags.get("addr:town") or
                tags.get("addr:district") or tags.get("addr:state") or "Nearby")
        loc = (tags.get("addr:street") or tags.get("addr:suburb") or
               tags.get("addr:housename") or "")
        amen = []
        if tags.get("wheelchair") == "yes":
            amen.append("Wheelchair Access")
        out.append({
            "osm_id": f"{el['type'][0]}{el['id']}",     # e.g. n123, w456
            "name": name[:150], "location": loc[:200], "city": city[:100],
            "lat": round(float(lat), 6), "lng": round(float(lng), 6),
            "amenities": ",".join(amen),
        })
    return out


def ensure_cinemas_near(lat, lng):
    """
    If we know fewer than MIN_LOCAL_THEATRES cinemas within FETCH_RADIUS_KM of
    (lat, lng), fetch real ones from OSM, store them, and seed demo shows.
    Never raises: on any failure the caller just gets the cinemas it already has.
    Returns the number of cinemas added.
    """
    cell = (round(lat, 1), round(lng, 1))          # ~11 km grid cell
    if time.time() - _asked.get(cell, 0) < CACHE_SECONDS:
        return 0
    conn = None
    try:
        conn = get_connection()
        _ensure_column(conn)
        cur = conn.cursor()
        cur.execute("SELECT lat, lng FROM theatres WHERE lat IS NOT NULL AND lng IS NOT NULL")
        near = sum(1 for a, b in cur.fetchall()
                   if haversine_km(lat, lng, float(a), float(b)) <= FETCH_RADIUS_KM)
        if near >= MIN_LOCAL_THEATRES:
            _asked[cell] = time.time()
            return 0

        found = parse_elements(_query_overpass(lat, lng, FETCH_RADIUS_KM))
        found.sort(key=lambda t: haversine_km(lat, lng, t["lat"], t["lng"]))
        _asked[cell] = time.time()                 # remember even if 0 results

        new_ids = []
        for t in found[:MAX_NEW_PER_FETCH]:
            cur.execute("SELECT id FROM theatres WHERE osm_id = %s", (t["osm_id"],))
            if cur.fetchone():
                continue
            cur.execute(
                "INSERT INTO theatres (name, location, city, lat, lng, amenities, osm_id) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (t["name"], t["location"], t["city"], t["lat"], t["lng"],
                 t["amenities"], t["osm_id"]))
            new_ids.append(cur.lastrowid)
        conn.commit()
        cur.close()
        if new_ids:
            seed_upcoming_shows(conn, 3, theatre_ids=new_ids)
        return len(new_ids)
    except Exception as e:
        print(f"[osm] could not fetch cinemas: {e}")
        return 0
    finally:
        if conn:
            conn.close()