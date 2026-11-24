from flask import Flask, jsonify, request
from datetime import datetime, timedelta
import os
import random
import threading
import uuid
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room, leave_room

from database import get_connection
from scheduler import start_scheduler
from activity import log_event, get_log
from payment_config import PAYMENT_MODE, RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET
from geo import haversine_km, seat_price, seat_tier
from osm_cinemas import ensure_cinemas_near
from acid_lab import (ensure_tables as ensure_lab_tables, run_atomicity, run_consistency,
                      run_isolation, run_durability, check_durability)

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# PAYMENT_MODE = "mock"     -> demo checkout, no Razorpay account needed
# PAYMENT_MODE = "razorpay" -> real Razorpay (test keys) with signature verification
# razorpay is only imported in that mode, so mock mode runs even if the
# razorpay package isn't installed or is broken on your Python version.
if PAYMENT_MODE == "razorpay":
    import razorpay
    razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
else:
    razorpay = None
    razorpay_client = None

HOLD_DURATION_MINUTES = 5

BOOKING_COUNTERS = threading.Semaphore(3)

def _theatre_row(t):
    """Normalise a theatres row for JSON (Decimal -> float, amenities -> list)."""
    return {
        "id": t["id"],
        "name": t["name"],
        "location": t["location"],
        "city": t["city"],
        "lat": float(t["lat"]) if t["lat"] is not None else None,
        "lng": float(t["lng"]) if t["lng"] is not None else None,
        "amenities": [a.strip() for a in (t["amenities"] or "").split(",") if a.strip()],
    }


@app.route("/api/dbtest")
def dbtest():
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SHOW TABLES")
        tables = [r[0] for r in cur.fetchall()]
        cur.close()
        conn.close()
        return jsonify({"ok": True, "tables": tables})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/theatres/nearby", methods=["GET"])
def get_nearby_theatres():

    try:
        lat = float(request.args["lat"])
        lng = float(request.args["lng"])
        radius = float(request.args.get("radius_km", 25))
    except (KeyError, ValueError):
        return jsonify({"error": "lat and lng (numbers) are required"}), 400

    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return jsonify({"error": "lat/lng out of range"}), 400
    radius = max(1.0, min(radius, 1000.0))
    ensure_cinemas_near(lat, lng)

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id, name, location, city, lat, lng, amenities FROM theatres "
            "WHERE lat IS NOT NULL AND lng IS NOT NULL"
        )
        theatres = [_theatre_row(t) for t in cursor.fetchall()]

        # what's on soon at each theatre (one grouped query, not one per theatre)
        cursor.execute("""
            SELECT theatre_id, COUNT(DISTINCT movie_id) AS movie_count,
                   MIN(show_time) AS next_show, MIN(price) AS from_price
            FROM shows WHERE show_time >= NOW() GROUP BY theatre_id
        """)
        summary = {r["theatre_id"]: r for r in cursor.fetchall()}
    finally:
        cursor.close()
        conn.close()

    for t in theatres:
        t["distance_km"] = round(haversine_km(lat, lng, t["lat"], t["lng"]), 1)
        info = summary.get(t["id"])
        t["movie_count"] = info["movie_count"] if info else 0
        t["next_show"] = info["next_show"].isoformat() if info and info["next_show"] else None
        t["from_price"] = float(info["from_price"]) if info and info["from_price"] is not None else None

    theatres.sort(key=lambda t: t["distance_km"])
    return jsonify({
        "theatres": [t for t in theatres if t["distance_km"] <= radius],
        "nearest": theatres[0] if theatres else None,
    })


@app.route("/api/locations/search", methods=["GET"])
def search_locations():
  
    q = (request.args.get("q") or "").strip().lower()
    if len(q) < 2:
        return jsonify([])

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT name, location, city, lat, lng FROM theatres "
        "WHERE lat IS NOT NULL AND lng IS NOT NULL"
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    results = []

    by_city = {}
    for r in rows:
        by_city.setdefault(r["city"], []).append(r)
    for city, ts in by_city.items():
        if city and q in city.lower():
            results.append({
                "type": "city",
                "label": city,
                "sub": f"{len(ts)} cinema{'s' if len(ts) != 1 else ''}",
                "lat": sum(float(t["lat"]) for t in ts) / len(ts),
                "lng": sum(float(t["lng"]) for t in ts) / len(ts),
            })

    for r in rows:
        if q in (r["location"] or "").lower() or q in r["name"].lower():
            results.append({
                "type": "area",
                "label": f"{r['location']}, {r['city']}",
                "sub": r["name"],
                "lat": float(r["lat"]),
                "lng": float(r["lng"]),
            })

    return jsonify(results[:8])


def _to_float(base_price):
    return float(base_price) if base_price is not None else 250.0


@app.route("/api/theatres/<int:theatre_id>/shows", methods=["GET"])
def get_shows_for_theatre(theatre_id):
    """Upcoming shows at one theatre, with live availability for each."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT
            sh.id AS show_id,
            m.id AS movie_id,
            m.title,
            m.duration_min,
            m.genre,
            m.language,
            sh.show_time,
            sh.price,
            (SELECT COUNT(*) FROM seats s WHERE s.show_id = sh.id AND s.status = 'available') AS available_seats,
            (SELECT COUNT(*) FROM seats s WHERE s.show_id = sh.id) AS total_seats
        FROM shows sh
        JOIN movies m ON sh.movie_id = m.id
        WHERE sh.theatre_id = %s AND sh.show_time >= NOW()
        ORDER BY m.id, sh.show_time
    """, (theatre_id,))
    shows = cursor.fetchall()

    for s in shows:
        s["show_time"] = s["show_time"].isoformat()
        s["price"] = _to_float(s["price"])

    cursor.close()
    conn.close()
    return jsonify(shows)


@app.route("/api/shows/<int:show_id>/seats", methods=["GET"])
def get_seats(show_id):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT s.id, s.seat_no, s.status, s.held_by, sh.price AS base_price "
        "FROM seats s JOIN shows sh ON s.show_id = sh.id "
        "WHERE s.show_id = %s ORDER BY s.id",
        (show_id,)
    )
    seats = cursor.fetchall()
    cursor.close()
    conn.close()

    for s in seats:
        base = s.pop("base_price")
        s["price"] = seat_price(base, s["seat_no"])
        s["tier"] = seat_tier(s["seat_no"])[0]
    return jsonify(seats)


@app.route("/api/users/lookup", methods=["POST"])
def lookup_or_create_user():
    data = request.get_json()
    name = (data.get("name") or "").strip()

    if not name:
        return jsonify({"error": "name is required"}), 400

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("SELECT id, name FROM users WHERE name = %s", (name,))
        user = cursor.fetchone()

        if user:
            conn.commit()
            return jsonify(user)

        fake_email = f"{name.lower().replace(' ', '')}_{random.randint(1000,9999)}@cinesync.local"
        cursor.execute("INSERT INTO users (name, email) VALUES (%s, %s)", (name, fake_email))
        conn.commit()

        return jsonify({"id": cursor.lastrowid, "name": name})

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/api/shows/<int:show_id>/hold-group", methods=["POST"])
def hold_group(show_id):

    data = request.get_json()
    user_id = data.get("user_id")
    seat_ids = sorted(data.get("seat_ids", []))  # <-- the deadlock-avoidance bit

    if not seat_ids:
        return jsonify({"error": "no seats specified"}), 400

    with BOOKING_COUNTERS:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            locked_seats = []
            for seat_id in seat_ids:
                cursor.execute("SELECT * FROM seats WHERE id = %s FOR UPDATE", (seat_id,))
                seat = cursor.fetchone()

                already_mine = (
                    seat is not None and seat["status"] == "held"
                    and seat["held_by"] == user_id
                )
                wrong_show = seat is not None and seat["show_id"] != show_id
                if seat is None or wrong_show or (seat["status"] != "available" and not already_mine):
                    conn.rollback()
                    bad_label = seat["seat_no"] if seat else seat_id
                    log_event(f"Group hold REJECTED for user {user_id} - seat {bad_label} unavailable")
                    return jsonify({"error": f"seat {bad_label} is not available, whole group hold cancelled"}), 409

                locked_seats.append(seat)

            held_until = datetime.now() + timedelta(minutes=HOLD_DURATION_MINUTES)
            for seat_id in seat_ids:
                cursor.execute(
                    "UPDATE seats SET status='held', held_by=%s, held_until=%s WHERE id=%s",
                    (user_id, held_until, seat_id)
                )
            conn.commit()

            seat_labels = ", ".join(s["seat_no"] for s in locked_seats)
            log_event(f"Group LOCKED by user {user_id}: seats {seat_labels} ({len(seat_ids)} seats)")

            return jsonify({
                "message": "group held",
                "held_until": held_until.isoformat(),
                "hold_seconds": HOLD_DURATION_MINUTES * 60,
                "seat_ids": seat_ids
            })

        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()


@app.route("/api/holds/release", methods=["POST"])
def release_holds():
 data = request.get_json()
    user_id = data.get("user_id")
    seat_ids = data.get("seat_ids", [])
    if not seat_ids:
        return jsonify({"released": 0})

    conn = get_connection()
    cursor = conn.cursor()
    try:
        placeholders = ",".join(["%s"] * len(seat_ids))
        cursor.execute(
            f"UPDATE seats SET status='available', held_by=NULL, held_until=NULL "
            f"WHERE id IN ({placeholders}) AND status='held' AND held_by=%s",
            (*seat_ids, user_id)
        )
        released = cursor.rowcount
        conn.commit()
        if released:
            log_event(f"User {user_id} released {released} held seat(s) voluntarily")
        return jsonify({"released": released})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/api/payment/create-order", methods=["POST"])
def create_payment_order():

    data = request.get_json()
    user_id = data.get("user_id")
    seat_ids = data.get("seat_ids", [])

    if not seat_ids:
        return jsonify({"error": "seat_ids are required"}), 400

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # safety check - make sure these seats are actually held by
        # this user before we even bother creating a payment order
        placeholders = ",".join(["%s"] * len(seat_ids))
        cursor.execute(
            f"SELECT s.id, s.seat_no, s.status, s.held_by, sh.price AS base_price "
            f"FROM seats s JOIN shows sh ON s.show_id = sh.id "
            f"WHERE s.id IN ({placeholders})",
            tuple(seat_ids)
        )
        seats = cursor.fetchall()

        if len(seats) != len(set(seat_ids)):
            return jsonify({"error": "unknown seat in request"}), 400

        for s in seats:
            if s["status"] != "held" or s["held_by"] != user_id:
                return jsonify({"error": "one or more seats are not held by you anymore"}), 409

        # the amount is computed HERE from the database - whatever the
        # browser claims it costs is ignored
        amount = sum(seat_price(s["base_price"], s["seat_no"]) for s in seats)

        if PAYMENT_MODE == "razorpay":
            razorpay_order = razorpay_client.order.create({
                "amount": int(float(amount) * 100),  # Razorpay wants paise, not rupees
                "currency": "INR",
                "payment_capture": 1
            })
        else:
            # demo order: same shape as a Razorpay order, created locally
            razorpay_order = {"id": "mock_order_" + uuid.uuid4().hex[:14], "amount": int(amount) * 100}

        cursor.execute(
            "INSERT INTO payment_orders (razorpay_order_id, user_id, seat_ids, amount, status) "
            "VALUES (%s, %s, %s, %s, 'created')",
            (razorpay_order["id"], user_id, ",".join(map(str, seat_ids)), amount)
        )
        conn.commit()

        log_event(f"Razorpay order {razorpay_order['id']} created for user {user_id} (amount Rs.{amount})")

        return jsonify({
            "order_id": razorpay_order["id"],
            "mode": PAYMENT_MODE,
            "key_id": RAZORPAY_KEY_ID if PAYMENT_MODE == "razorpay" else None,
            "amount": razorpay_order["amount"],
            "amount_rupees": amount
        })

    except Exception as e:
        conn.rollback()
        return jsonify({"error": f"could not create payment order: {e}"}), 500
    finally:
        cursor.close()
        conn.close()


class SimulatedCrash(Exception):
    """Raised on purpose in demo mode, to SHOW what ROLLBACK does."""


def _snapshot(order_ref):
    """
    What the database looks like for this order, read through a BRAND-NEW
    connection. After a COMMIT that proves durability (a different session
    sees the data); after a ROLLBACK it proves atomicity (nothing leaked).
    """
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id, seat_ids, status FROM payment_orders WHERE razorpay_order_id = %s",
            (order_ref,)
        )
        order = cursor.fetchone()
        if not order:
            return None
        ids = [int(x) for x in order["seat_ids"].split(",")]
        marks = ",".join(["%s"] * len(ids))
        cursor.execute(f"SELECT seat_no, status FROM seats WHERE id IN ({marks}) ORDER BY id", tuple(ids))
        seats = cursor.fetchall()
        cursor.execute("SELECT COUNT(*) AS n FROM bookings WHERE group_order_id = %s", (order["id"],))
        n_bookings = cursor.fetchone()["n"]
        cursor.execute(
            "SELECT COUNT(*) AS n FROM payments p JOIN bookings b ON p.booking_id = b.id "
            "WHERE b.group_order_id = %s", (order["id"],)
        )
        n_payments = cursor.fetchone()["n"]
        conn.commit()   # end the read-only snapshot transaction
        return {
            "order_status": order["status"],
            "seats": [{"seat_no": s["seat_no"], "status": s["status"]} for s in seats],
            "bookings": n_bookings,
            "payments": n_payments,
        }
    finally:
        cursor.close()
        conn.close()


def _confirm_booking(order_ref, payment_id, crash=False):

    trace = []

    def step(kind, text):
        trace.append({"kind": kind, "text": text})

    status, payload = 500, {"error": "unexpected error"}

    with BOOKING_COUNTERS:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            step("sql", "BEGIN   (autocommit is off, so everything below is ONE transaction)")
            cursor.execute(
                "SELECT * FROM payment_orders WHERE razorpay_order_id = %s FOR UPDATE",
                (order_ref,)
            )
            order = cursor.fetchone()
            step("lock", f"SELECT * FROM payment_orders WHERE razorpay_order_id = '{order_ref}' FOR UPDATE")

            if order is None or order["status"] != "created":
                conn.rollback()
                step("rollback", "ROLLBACK - order not found or already processed")
                status, payload = 404, {"error": "order not found or already processed"}
            else:
                seat_ids = sorted(int(x) for x in order["seat_ids"].split(","))
                user_id = order["user_id"]
                per_seat_amount = round(float(order["amount"]) / len(seat_ids), 2)

                booking_ids = []
                failure = None

                for n, seat_id in enumerate(seat_ids, start=1):
                    cursor.execute("SELECT * FROM seats WHERE id = %s FOR UPDATE", (seat_id,))
                    seat = cursor.fetchone()
                    label = seat["seat_no"] if seat else f"#{seat_id}"
                    step("lock", f"SELECT * FROM seats WHERE id = {seat_id} FOR UPDATE   (seat {label})")

                    # CONSISTENCY rule: only a seat HELD BY THIS USER may become booked
                    if seat is None or seat["status"] != "held" or seat["held_by"] != user_id:
                        conn.rollback()
                        step("error", f"Seat {label} is no longer held by this user")
                        step("rollback", "ROLLBACK - nothing from this transaction is kept")
                        log_event(f"Transaction ROLLED BACK for order {order_ref} - seat {label} no longer held")
                        failure = (409, {"error": f"seat {label} is no longer held by you, group booking cancelled"})
                        break

                    step("ok", f"Seat {label} is held by you, safe to book")

                    cursor.execute(
                        "INSERT INTO bookings (user_id, seat_id, state, group_order_id) VALUES (%s, %s, 'confirmed', %s)",
                        (user_id, seat_id, order["id"])
                    )
                    booking_id = cursor.lastrowid
                    booking_ids.append(booking_id)
                    step("sql", f"INSERT INTO bookings ... (seat {label})  -> booking #{booking_id}")

                    cursor.execute(
                        "INSERT INTO payments (booking_id, amount, status, razorpay_payment_id) "
                        "VALUES (%s, %s, 'success', %s)",
                        (booking_id, per_seat_amount, payment_id)
                    )
                    step("sql", f"INSERT INTO payments ... amount {per_seat_amount}")

                    cursor.execute("UPDATE seats SET status='booked' WHERE id=%s", (seat_id,))
                    step("sql", f"UPDATE seats SET status='booked' WHERE id = {seat_id}")

                    # demo only: die after the FIRST seat is fully written, so there is
                    # something half-finished to roll back
                    if crash and n == 1:
                        step("crash", "Simulated crash: the server dies right here, BEFORE commit")
                        raise SimulatedCrash()

                if failure:
                    status, payload = failure
                else:
                    cursor.execute("UPDATE payment_orders SET status='paid' WHERE id = %s", (order["id"],))
                    step("sql", "UPDATE payment_orders SET status='paid'")
                    conn.commit()
                    step("commit", f"COMMIT   -> {len(seat_ids)} booking(s), {len(seat_ids)} payment(s) and "
                                   f"{len(seat_ids)} seat update(s) become permanent together")
                    log_event(f"Transaction COMMITTED - {len(seat_ids)} seat(s) booked for order {order_ref}, payment {payment_id}")
                    status, payload = 200, {
                        "message": "group booking confirmed",
                        "booking_ids": booking_ids,
                        "group_order_id": order["id"],
                        "payment_id": payment_id,
                    }

        except SimulatedCrash:
            conn.rollback()
            step("rollback", "ROLLBACK - the database undoes every change since BEGIN: "
                             "the booking, the payment and the seat update all vanish together")
            log_event(f"Transaction ROLLED BACK after simulated crash (order {order_ref}) - nothing was kept")
            status, payload = 500, {
                "error": "Simulated server crash in the middle of the transaction. Everything was rolled back.",
                "rolled_back": True,
            }

        except Exception as e:
            conn.rollback()
            step("error", str(e))
            step("rollback", "ROLLBACK - unexpected error, nothing was kept")
            status, payload = 500, {"error": str(e), "rolled_back": True}

        finally:
            cursor.close()
            conn.close()

    payload["trace"] = trace
    try:
        snap = _snapshot(order_ref)
        if snap:
            payload["state_after"] = snap
    except Exception:
        pass   # the snapshot is a bonus for the UI; never let it break the response
    return status, payload


@app.route("/api/payment/verify", methods=["POST"])
def verify_payment():
    """
    Called after checkout finishes.

    razorpay mode: verify the payment signature (proves the payment really
    came from Razorpay), then run the booking transaction.

    mock mode: there is no gateway. The browser says which outcome to simulate:
        success -> normal booking transaction (COMMIT)
        decline -> the "bank" says no; no booking transaction is even started
        crash   -> the transaction starts, then the server "dies" halfway: ROLLBACK
    """
    data = request.get_json()
    order_ref = data.get("razorpay_order_id", "")
    crash = False

    if PAYMENT_MODE == "razorpay":
        try:
            razorpay_client.utility.verify_payment_signature({
                "razorpay_order_id": data["razorpay_order_id"],
                "razorpay_payment_id": data["razorpay_payment_id"],
                "razorpay_signature": data["razorpay_signature"]
            })
        except razorpay.errors.SignatureVerificationError:
            log_event("Payment signature verification FAILED - possible tampering, booking rejected")
            return jsonify({"error": "payment signature verification failed"}), 400
        payment_id = data["razorpay_payment_id"]
    else:
        if not str(order_ref).startswith("mock_order_"):
            return jsonify({"error": "not a demo order"}), 400
        outcome = data.get("outcome", "success")
        if outcome not in ("success", "decline", "crash"):
            return jsonify({"error": "unknown outcome"}), 400
        payment_id = data.get("razorpay_payment_id") or "mock_pay_" + uuid.uuid4().hex[:10]

        if outcome == "decline":
            return _decline_mock_payment(order_ref)

        crash = (outcome == "crash")
        log_event(f"DEMO payment accepted ({'will crash mid-transaction' if crash else 'success'}) - no signature check in mock mode")

    status, payload = _confirm_booking(order_ref, payment_id, crash=crash)
    return jsonify(payload), status


def _decline_mock_payment(order_ref):
    """The simulated bank says no. No booking transaction is started at all."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE payment_orders SET status='failed' WHERE razorpay_order_id = %s AND status='created'",
            (order_ref,)
        )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

    log_event(f"DEMO payment DECLINED for order {order_ref} - no booking rows written, seats stay held")
    trace = [
        {"kind": "gateway", "text": "The (simulated) bank declined the card"},
        {"kind": "ok", "text": "No BEGIN was issued: the booking transaction only starts AFTER money is confirmed"},
        {"kind": "ok", "text": "Seats stay held for you until the timer runs out, so you can try again"},
    ]
    payload = {"error": "Payment declined (simulated)", "trace": trace}
    try:
        snap = _snapshot(order_ref)
        if snap:
            payload["state_after"] = snap
    except Exception:
        pass
    return jsonify(payload), 402



@app.route("/api/food-items", methods=["GET"])
def get_food_items():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, name, price FROM food_items")
    items = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(items)


@app.route("/api/bookings/<int:booking_id>/food-order", methods=["POST"])
def add_food_order(booking_id):
    data = request.get_json()
    items = data.get("items", [])

    if not items:
        return jsonify({"error": "no items provided"}), 400

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("SELECT state FROM bookings WHERE id = %s", (booking_id,))
        booking = cursor.fetchone()

        if booking is None or booking["state"] != "confirmed":
            conn.rollback()
            return jsonify({"error": "booking not found or not confirmed"}), 404

        for item in items:
            cursor.execute(
                "INSERT INTO food_orders (booking_id, food_item_id, quantity) VALUES (%s, %s, %s)",
                (booking_id, item["food_item_id"], item.get("quantity", 1))
            )

        conn.commit()
        return jsonify({"message": "food order added"})

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/api/users/<int:user_id>/bookings", methods=["GET"])
def get_user_bookings(user_id):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            b.id AS booking_id,
            b.state,
            b.group_order_id,
            b.created_at,
            s.seat_no,
            m.title AS movie_title,
            t.name AS theatre_name,
            sh.show_time,
            p.amount,
            p.status AS payment_status,
            p.razorpay_payment_id
        FROM bookings b
        JOIN seats s ON b.seat_id = s.id
        JOIN shows sh ON s.show_id = sh.id
        JOIN movies m ON sh.movie_id = m.id
        JOIN theatres t ON sh.theatre_id = t.id
        LEFT JOIN payments p ON p.booking_id = b.id
        WHERE b.user_id = %s
        ORDER BY b.created_at DESC
    """, (user_id,))

    bookings = cursor.fetchall()

    for b in bookings:
        if b.get("created_at"):
            b["created_at"] = b["created_at"].isoformat()
        if b.get("show_time"):
            b["show_time"] = b["show_time"].isoformat()

    cursor.close()
    conn.close()
    return jsonify(bookings)


def _run_lab(fn, *args):
    try:
        ensure_lab_tables()          # creates the lab_* tables the first time
        return jsonify(fn(*args))
    except Exception as e:           # show the real problem in the UI instead of a blank 500
        return jsonify({"error": f"ACID lab failed: {e}"}), 500


@app.route("/api/payment/config", methods=["GET"])
def payment_mode():
    return jsonify({"mode": PAYMENT_MODE})


@app.route("/api/acid/atomicity", methods=["POST"])
def acid_atomicity():
    data = request.get_json(silent=True) or {}
    return _run_lab(run_atomicity, bool(data.get("safe", True)))


@app.route("/api/acid/consistency", methods=["POST"])
def acid_consistency():
    data = request.get_json(silent=True) or {}
    return _run_lab(run_consistency, data.get("scenario", "double_booking"))


@app.route("/api/acid/isolation", methods=["POST"])
def acid_isolation():
    data = request.get_json(silent=True) or {}
    return _run_lab(run_isolation, bool(data.get("safe", True)))


@app.route("/api/acid/durability", methods=["POST"])
def acid_durability():
    return _run_lab(run_durability)


@app.route("/api/acid/durability/check", methods=["GET"])
def acid_durability_check():
    return _run_lab(check_durability)


@app.route("/api/activity-log", methods=["GET"])
def activity_log():
    return jsonify(get_log())


@app.route("/api/movies", methods=["GET"])
def get_movies():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, title, duration_min, genre, language FROM movies ORDER BY id")
    movies = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(movies)


@app.route("/api/movies/<int:movie_id>/reviews", methods=["GET"])
def get_reviews(movie_id):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT r.id, r.rating, r.comment, r.created_at, u.name AS user_name
        FROM reviews r
        JOIN users u ON r.user_id = u.id
        WHERE r.target_type = 'movie' AND r.target_id = %s
        ORDER BY r.created_at ASC
    """, (movie_id,))
    reviews = cursor.fetchall()

    for r in reviews:
        if r.get("created_at"):
            r["created_at"] = r["created_at"].isoformat()

    cursor.close()
    conn.close()
    return jsonify(reviews)


@socketio.on("join_movie")
def handle_join_movie(data):
    """Each movie gets its own 'room' so chat doesn't leak across movies."""
    room = f"movie_{data['movie_id']}"
    join_room(room)


@socketio.on("leave_movie")
def handle_leave_movie(data):
    """Without this, switching movies left you subscribed to every room you'd ever opened."""
    leave_room(f"movie_{data['movie_id']}")


@socketio.on("send_message")
def handle_send_message(data):

    comment = str(data.get("comment", "")).strip()[:500]
    try:
        rating = max(1, min(5, int(data.get("rating", 5))))
    except (TypeError, ValueError):
        rating = 5
    if not comment:
        return

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            "INSERT INTO reviews (user_id, target_type, target_id, rating, comment) "
            "VALUES (%s, 'movie', %s, %s, %s)",
            (data["user_id"], data["movie_id"], rating, comment)
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[socketio] failed to save review: {e}")
    finally:
        cursor.close()
        conn.close()

    room = f"movie_{data['movie_id']}"
    emit("new_message", {
        "movie_id": data["movie_id"],
        "user_name": data["user_name"],
        "rating": rating,
        "comment": comment
    }, room=room)


start_scheduler()   # runs at import, so it also starts under gunicorn
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, allow_unsafe_werkzeug=True)
