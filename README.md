# CineSync - Phase 3

Movie ticket booking system built for our OS + DBMS project. Core idea:
two people should never be able to book the same seat, a group of seats
booked together should either ALL succeed or ALL fail, and now - real
payment, real-time chat, and multiple theatres.

## What's new in Phase 3.1

- **Demo payment mode (no Razorpay account or PAN needed).** `PAYMENT_MODE = "mock"`
  in `backend/payment_config.py` (the default). Set it to `"razorpay"` and fill in
  test keys to use real Razorpay. In mock mode the `razorpay` package is never
  imported, so it can't break the app.
- **ACID shown, not just claimed.** On the demo checkout you can choose
  *Pay successfully*, *Decline the card*, or *Crash the server mid-booking*. The
  pay and ticket screens then show the real transaction as a timeline
  (BEGIN, locks, INSERTs, COMMIT or ROLLBACK) plus what a brand-new database
  connection sees afterwards.
- **ACID Lab** (nav bar): four real MySQL experiments, each runnable with and
  without the protection:
  | Letter | Experiment | What you see |
  |---|---|---|
  | A | 3 seats, crash after the 2nd | transaction: 0 rows left. Autocommit: 2 orphan rows |
  | C | double-book a seat / overspend a wallet | UNIQUE and CHECK rules refuse it, transaction rolls back |
  | I | two people book seat L1 at once | `FOR UPDATE`: one winner. No lock: both told "booked" (lost update) |
  | D | COMMIT, read back on a new connection | plus `innodb_flush_log_at_trx_commit`; stop/start MySQL and press "Check after restart" |
  The lab uses its own `lab_*` tables (created automatically on first run), so it never touches real bookings. CHECK rules need MySQL 8.0.16+.
- **Bright and dark themes.** Bright and colourful by default; the sun/moon
  button switches (and remembers your choice).

## What's new in Phase 3

- **Cinemas near you** - type a city/area/pincode or tap "Use my location".
  `GET /api/theatres/nearby` returns cinemas sorted by real distance
  (haversine formula, `backend/geo.py`). A radius slider, sort (nearest /
  cheapest / earliest) and amenity filters sit on top, and an interactive
  radar shows where each cinema is relative to you.
- **Showtimes with live availability** - pick a cinema, then a day, a movie
  and a time. Each time shows how full the show is.
- **New seat map** - screen glows in the movie's colour, "Pick best seats"
  finds N seats together near the centre, row tiers (Classic / Prime /
  Premium) have different prices, and a hold timer counts down on the pay screen.
- **Ticket-style UI** throughout, mobile friendly.
- **Fixes found while rebuilding** (worth knowing for your viva):
  - Price was sent by the browser to `/create-order`; it is now computed on the
    server from the seats (`geo.seat_price`), so it can't be edited in dev tools.
  - Going back from the payment screen left your own seats stuck as "held" and
    you couldn't re-select them. Re-holding your own seats now works, and
    `POST /api/holds/release` frees them immediately.
  - Chat messages and names were inserted into the page as raw HTML (stored
    XSS). Everything is escaped now.
  - Chat rooms were never left, so old movies' messages leaked into the open
    one. Added `leave_movie` and a `movie_id` check.
  - Show dates were hard-coded to October, so shows expired. `seed_shows.py`
    generates upcoming shows relative to today.

> Theatre names/coordinates in the sample data are **demo values** (approximate
> lat/lng). Replace them with real venues before showing this as real data.

## What was in Phase 2

- **3 theatres**, each showing all 5 movies - pick a theatre first, then a movie
- **Group/family booking** - choose how many seats you need (1-6), then
  pick exactly that many on the seat map, all locked and booked together
  as one atomic unit
- **Real Razorpay payment (test mode)** - not mocked anymore. An actual
  order is created through Razorpay's API, you pay through their real
  checkout popup (with test card numbers, no real money), and we verify
  the payment signature before confirming anything
- **True live chat** via Socket.IO - messages appear for everyone
  watching that movie's chat instantly, no polling/refreshing involved
- Everything from Phase 2 still works: row-level locking, the booking
  semaphore, the background scheduler, the deadlock demo, food ordering,
  and the View/Trigger/Stored Procedure

## Setup

### 1. Database

**Fresh install** (new database, nothing to lose):
```
mysql -u root -p < backend/schema.sql
cd backend && python seed_shows.py      # creates shows + seats for the next 3 days
```
Run `python seed_shows.py` again any day to top up upcoming shows (it only adds what's missing).

**Already have a Phase 3 database and don't want to lose your bookings?**
Don't run schema.sql - instead, after completing step 2 below, run:
```
python migrate_to_phase4.py
```
This adds the location columns (city, lat, lng, amenities), movie genre/language,
show prices, the extra demo cinemas, and fresh upcoming shows - checking first
so it is safe to run twice. (On a Phase 2 database run `migrate_to_phase3.py` first.)

### 2. Python setup

```
cd backend
pip install -r requirements.txt
```

Open `database.py` and put in your MySQL password.

### 3. Razorpay test keys (required for payment to work)

1. Sign up free at https://dashboard.razorpay.com/signup
2. Make sure you're in **Test Mode** (toggle, top-left of the dashboard)
3. Settings -> API Keys -> Generate Test Key
4. Open `backend/payment_config.py` and paste your Key Id and Key Secret

Without this step, the app still runs, but creating a payment order will
fail with an authentication error from Razorpay.

### 4. Run the backend

```
python app.py
```

### 5. Open the frontend

Serve the folder over localhost (still no build step):
```
cd frontend
python -m http.server 8000
```
then open http://localhost:8000. Don't double-click `index.html` this time:
browsers only offer "Use my location" on secure origins, and `http://localhost`
counts as secure while `file://` is unreliable. Typing a location works either way.

## How to demo

1. Enter a name and a location (try `Dehradun`, then a locality like `Rajpur`, or Use my location)
2. Drag the radius slider, change the sort, hover a cinema and watch its pin on the radar
3. Open a cinema, choose a day and a showtime
4. Set the seat count (try 3 - a "family" booking) and tap "Pick best seats", or click seats yourself
5. Continue to payment
6. Razorpay's real checkout popup opens - use test card
   **4111 1111 1111 1111**, any future expiry, any CVV, any name
7. After payment, the booking confirms, food ordering appears, and it
   shows up grouped in "My Bookings"
8. Go to "Live chat" - open the SAME movie in a second browser tab
   with a different name, send a message from one tab, watch it appear
   instantly in the other - that's the real-time Socket.IO part, not polling

### Concurrency demo (still the most important one)
Two tabs, same theatre, same movie, same seat count, try to grab the
SAME seat in both - one succeeds, the other gets rejected. Watch the
System Activity panel on the booking screen for the live lock/reject messages.

### Deadlock demo
```
python deadlock_demo.py
```
Reset seats 1 and 2 to 'available' first if they aren't already.

### DBMS objects
```sql
SELECT * FROM available_seats_per_show;                      -- view
SELECT * FROM seat_audit_log ORDER BY changed_at DESC;        -- trigger (book any seat first)
CALL ConfirmBooking(1, 1, 250.00, @result); SELECT @result;   -- stored procedure
```

## Clearing demo data between runs

```sql
USE cinesync;
DELETE FROM food_orders;
DELETE FROM payments;
DELETE FROM bookings;
DELETE FROM payment_orders;
DELETE FROM seat_audit_log;
UPDATE seats SET status='available', held_by=NULL, held_until=NULL;
ALTER TABLE bookings AUTO_INCREMENT = 1;
ALTER TABLE payments AUTO_INCREMENT = 1;
ALTER TABLE payment_orders AUTO_INCREMENT = 1;
```

## OS and DBMS concepts, where to find them

| Concept | File | Notes |
|---|---|---|
| Row-level locking / critical section | `app.py` - `hold_group()` | `SELECT ... FOR UPDATE` on each seat |
| Deadlock prevention | `app.py` - `hold_group()` | seats always locked in sorted ID order |
| Deadlock + detection | `deadlock_demo.py` | deliberately skips the sorted-order safeguard to trigger a real deadlock |
| Semaphore (bounded resource) | `app.py` - `BOOKING_COUNTERS` | max 3 concurrent booking operations |
| Background thread / scheduling | `scheduler.py` | separate OS thread, polls every 30s |
| Great-circle distance (location search) | `geo.py` - `haversine_km()` | used by `/api/theatres/nearby`; at scale you would pre-filter with an indexed bounding box or a MySQL spatial index |
| Transaction (ACID) | `app.py` - `verify_payment()` | all bookings+payments in a group commit or roll back together |
| View | `schema.sql` | `available_seats_per_show` |
| Trigger | `schema.sql` | `seat_status_change`, fires on its own |
| Stored procedure | `schema.sql` | `ConfirmBooking` - not called by the live app, shown separately |

## Folder structure

```
cinesync/
├── backend/
│   ├── app.py                   - Flask + Socket.IO: theatres, group booking, Razorpay, live chat
│   ├── scheduler.py             - background thread, releases expired holds
│   ├── activity.py              - shared live activity log
│   ├── database.py              - MySQL connection helper
│   ├── payment_config.py        - Razorpay test key placeholders (fill these in)
│   ├── deadlock_demo.py         - standalone deadlock trigger + detection demo
│   ├── geo.py                   - haversine distance + server-side seat pricing (pure functions)
│   ├── seed_shows.py            - creates upcoming shows + seats relative to today (re-runnable)
│   ├── migrate_to_phase4.py     - upgrades a Phase 3 database to Phase 4
│   ├── migrate_to_phase3.py     - safely upgrades an existing Phase 2 database
│   ├── schema.sql               - full schema, fresh install
│   └── requirements.txt
└── frontend/
    ├── index.html
    ├── style.css
    └── script.js
```
