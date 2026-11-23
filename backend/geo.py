import math

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1, lng1, lat2, lng2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


_TIERS = {
    "A": ("Classic", 0), "B": ("Classic", 0),
    "C": ("Prime", 50), "D": ("Prime", 50),
}
_PREMIUM = ("Premium", 120)   # row E and beyond (back rows, best view)


def seat_tier(seat_no):
    row = seat_no[0].upper()
    return _TIERS.get(row, _PREMIUM)


def seat_price(base_price, seat_no):
    return int(round(float(base_price))) + seat_tier(seat_no)[1]
