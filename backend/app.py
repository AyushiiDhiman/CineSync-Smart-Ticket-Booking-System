from flask import Flask, jsonify, request
from datetime import datetime, timedelta
import random
import threading
from flask_cors import CORS

from database import get_connection
from scheduler import start_scheduler
from activity import log_event, get_log

app = Flask(__name__)
CORS(app)

HOLD_DURATION_MINUTES = 5

BOOKING_COUNTERS = threading.Semaphore(3)


@app.route("/api/users/lookup", methods=["POST"])
def lookup_or_create_user(_cors_preflight_skip=False):
    """
    Takes a name, finds a matching user or creates a new one.
    Keeps it simple - just matching on name, no login/password system
    since that's not really the point of this project.
    """
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


@app.route("/api/movies", methods=["GET"])
def get_movies():
    """
    Returns all movies with their show info (one show per movie for now).
    This is what the movie selection screen loads first.
    """
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            m.id AS movie_id,
            m.title,
            m.duration_min,
            sh.id AS show_id,
            sh.show_time,
            t.name AS theatre_name
        FROM movies m
        JOIN shows sh ON sh.movie_id = m.id
        JOIN theatres t ON sh.theatre_id = t.id
        ORDER BY m.id
    """)
    movies = cursor.fetchall()

    for m in movies:
        if m.get("show_time"):
            m["show_time"] = m["show_time"].isoformat()

    cursor.close()
    conn.close()
    return jsonify(movies)


@app.route("/api/activity-log", methods=["GET"])
def activity_log():
    """
    This is what powers the 'System Activity' panel on the frontend -
    a live feed of locking/transaction/scheduler events so the OS and
    DBMS concepts are actually visible while using the app, not just
    hidden in a backend terminal nobody's looking at during a demo.
    """
    return jsonify(get_log())


@app.route("/api/movies/<int:movie_id>/reviews", methods=["GET"])
def get_reviews(movie_id):
    """Returns reviews for a movie, oldest first - like a chat log."""
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


@app.route("/api/movies/<int:movie_id>/reviews", methods=["POST"])
def post_review(movie_id):
    """
    Posts a new review/comment. The frontend polls the GET endpoint
    above every few seconds, so this is a 'live chat' in the sense
    that new comments from other users show up without a refresh -
    not a true websocket push, just simple polling, which is fine
    for what this project needs to demonstrate.
    """
    data = request.get_json()
    user_id = data.get("user_id")
    rating = data.get("rating", 5)
    comment = (data.get("comment") or "").strip()

    if not comment:
        return jsonify({"error": "comment is required"}), 400

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            "INSERT INTO reviews (user_id, target_type, target_id, rating, comment) "
            "VALUES (%s, 'movie', %s, %s, %s)",
            (user_id, movie_id, rating, comment)
        )
        conn.commit()
        return jsonify({"message": "posted"})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/api/shows/<int:show_id>/seats", methods=["GET"])
def get_seats(show_id):
    """Just returns the seat map for a show - no locking needed for a plain read."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT id, seat_no, status FROM seats WHERE show_id = %s ORDER BY seat_no",
        (show_id,)
    )
    seats = cursor.fetchall()

    cursor.close()
    conn.close()
    return jsonify(seats)


@app.route("/api/seats/<int:seat_id>/hold", methods=["POST"])
def hold_seat(seat_id):
    """
    This is the important one. A user clicks a seat -> we try to lock it.

    SELECT ... FOR UPDATE locks the row so no other request can touch it
    until we commit or rollback. If two requests hit this at the same
    time, MySQL makes the second one wait until the first finishes -
    that's what actually stops the double-booking.
    """
    data = request.get_json()
    user_id = data.get("user_id")

    # wait here if all 3 "counters" are busy - this is the semaphore
    # acquire, same idea as a process waiting for a free resource slot
    with BOOKING_COUNTERS:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            cursor.execute(
                "SELECT * FROM seats WHERE id = %s FOR UPDATE",
                (seat_id,)
            )
            seat = cursor.fetchone()

            if seat is None:
                conn.rollback()
                return jsonify({"error": "seat not found"}), 404

            if seat["status"] != "available":
                # someone already has it (or it's booked) - reject right away
                conn.rollback()
                log_event(f"Seat {seat['seat_no']} lock REJECTED for user {user_id} (already {seat['status']})")
                return jsonify({"error": "seat is not available"}), 409

            held_until = datetime.now() + timedelta(minutes=HOLD_DURATION_MINUTES)
            cursor.execute(
                "UPDATE seats SET status='held', held_by=%s, held_until=%s WHERE id=%s",
                (user_id, held_until, seat_id)
            )
            conn.commit()
            log_event(f"Seat {seat['seat_no']} LOCKED by user {user_id} (FOR UPDATE)")

            return jsonify({"message": "seat held", "held_until": held_until.isoformat()})

        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()


@app.route("/api/seats/<int:seat_id>/book", methods=["POST"])
def book_seat(seat_id):
    """
    Confirms the booking and 'pays' for it.

    Everything here happens in ONE transaction - booking row,
    payment row, and the seat status update all succeed together
    or none of them get saved. That's the atomicity part.

    Payment is mocked - no real gateway, just a random success/fail
    so we can actually demo the rollback case too.
    """
    data = request.get_json()
    user_id = data.get("user_id")
    amount = data.get("amount", 250.00)

    with BOOKING_COUNTERS:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            cursor.execute("SELECT * FROM seats WHERE id = %s FOR UPDATE", (seat_id,))
            seat = cursor.fetchone()

            if seat is None or seat["status"] != "held" or seat["held_by"] != user_id:
                conn.rollback()
                return jsonify({"error": "seat is not held by you, can't book it"}), 409

            # mock payment gateway - fails 10% of the time on purpose,
            # so we have something to show when demoing the rollback
            payment_success = random.random() > 0.10

            cursor.execute(
                "INSERT INTO bookings (user_id, seat_id, state) VALUES (%s, %s, %s)",
                (user_id, seat_id, "confirmed" if payment_success else "cancelled")
            )
            booking_id = cursor.lastrowid

            cursor.execute(
                "INSERT INTO payments (booking_id, amount, status) VALUES (%s, %s, %s)",
                (booking_id, amount, "success" if payment_success else "failed")
            )

            if not payment_success:
                # payment failed -> undo everything, seat goes back to available
                conn.rollback()
                log_event(f"Transaction ROLLED BACK for seat {seat['seat_no']} (payment failed)")
                return jsonify({"error": "payment failed, booking rolled back"}), 402

            cursor.execute(
                "UPDATE seats SET status='booked' WHERE id=%s",
                (seat_id,)
            )
            conn.commit()
            log_event(f"Transaction COMMITTED - seat {seat['seat_no']} booked, booking #{booking_id}")

            return jsonify({"message": "booking confirmed", "booking_id": booking_id})

        except Exception as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()


@app.route("/api/food-items", methods=["GET"])
def get_food_items():
    """Just the menu - static list, nothing fancy."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, name, price FROM food_items")
    items = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(items)


@app.route("/api/bookings/<int:booking_id>/food-order", methods=["POST"])
def add_food_order(booking_id):
    """
    Attaches food items to an already-confirmed booking.
    Keeping this separate from the seat/payment transaction on purpose -
    if food ordering fails, it shouldn't undo someone's seat booking.
    """
    data = request.get_json()
    items = data.get("items", [])  # [{food_item_id, quantity}, ...]

    if not items:
        return jsonify({"error": "no items provided"}), 400

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # make sure this booking is actually confirmed before attaching food to it
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
    """
    Booking history for 'My Bookings' - joins across seats, shows,
    movies and payments so the frontend gets everything in one call.
    """
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            b.id AS booking_id,
            b.state,
            b.created_at,
            s.seat_no,
            m.title AS movie_title,
            sh.show_time,
            p.amount,
            p.status AS payment_status
        FROM bookings b
        JOIN seats s ON b.seat_id = s.id
        JOIN shows sh ON s.show_id = sh.id
        JOIN movies m ON sh.movie_id = m.id
        LEFT JOIN payments p ON p.booking_id = b.id
        WHERE b.user_id = %s
        ORDER BY b.created_at DESC
    """, (user_id,))

    bookings = cursor.fetchall()

    # datetime objects don't serialize to JSON directly, so convert them
    for b in bookings:
        if b.get("created_at"):
            b["created_at"] = b["created_at"].isoformat()
        if b.get("show_time"):
            b["show_time"] = b["show_time"].isoformat()

    cursor.close()
    conn.close()
    return jsonify(bookings)


if __name__ == "__main__":
    # scheduler runs in a separate thread, keeps checking for expired holds
    start_scheduler()
    app.run(debug=True, port=5000)
