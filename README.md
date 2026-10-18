# CineSync

Movie ticket booking system built for our OS + DBMS mini project. Main idea:
two people should never be able to book the same seat, and a booking +
its payment should either both go through or neither should.

## What's actually done (Phase 2, ~60%)

- Seat booking with row-level locking (`SELECT ... FOR UPDATE`) - this is
  the core concurrency-control part
- Booking + mock payment as a single atomic transaction (commits or rolls
  back together)
- Background scheduler that releases seats held but never paid for, running
  on its own OS thread (see "OS concepts" below)
- A counting semaphore (`threading.Semaphore`) limiting how many booking
  requests run at once - a real OS resource-allocation primitive, written
  in our own code rather than relying on the database for it
- A standalone deadlock demo (`deadlock_demo.py`) that triggers and shows
  MySQL detecting a real deadlock between two transactions
- Working frontend: name entry, seat map, payment screen, food ordering,
  and a "My Bookings" history page, all connected to the backend

## DBMS objects (view, trigger, stored procedure)

Mentor asked for these specifically, so they're in `schema.sql` for fresh
installs, or in `add_db_objects.sql` if you already have a database set up
and don't want to lose data by rerunning the whole schema.

- **View** `available_seats_per_show` - run `SELECT * FROM available_seats_per_show;`
  to see available seat counts per movie without writing the join yourself
- **Trigger** `seat_status_change` - fires automatically on every seat update,
  logs it into `seat_audit_log`. Book any seat through the app, then run
  `SELECT * FROM seat_audit_log ORDER BY changed_at DESC;` to see it caught
  the change - we never call this trigger from the code, MySQL just does it
- **Stored procedure** `ConfirmBooking` - does the same booking+payment logic
  as the Flask route, but as a transaction fully inside the database. Not
  used by the actual app (we kept the Python version since it's easier to
  demo rollback from there), but good to show in the viva if asked
  specifically about stored procedures. Try it:
  ```sql
  CALL ConfirmBooking(1, 1, 250.00, @result);
  SELECT @result;
  ```
  (seat 1 needs to actually be held by user 1 first for this to succeed -
  hold it through the app, then run this before the 5-minute timer expires)

## OS concepts actually implemented (not just DB locking)

| Concept | Where |
|---|---|
| Background thread / daemon process | `scheduler.py` - runs on its own thread, separate from request handling |
| Counting semaphore (bounded resource allocation) | `app.py` - `BOOKING_COUNTERS`, limits concurrent booking operations to 3 |
| Deadlock detection | `deadlock_demo.py` - two transactions deadlock on purpose, MySQL's InnoDB detects and kills one |
| Mutual exclusion / critical section | `SELECT ... FOR UPDATE` in `app.py` - this one leans on the DB engine, worth being upfront about in viva |

Being honest in the report/viva about which parts are "we wrote this
ourselves" (scheduler thread, semaphore, deadlock demo) vs. "this is the
DB engine doing it for us" (row locking) actually looks stronger than
pretending it's all hand-rolled.

## Not done yet

- Any kind of real payment gateway (it's just a random success/fail, on purpose)
- True push-based live chat (reviews poll every 3 seconds instead of using websockets -
  it feels live but isn't a persistent connection)
- Styling polish / mobile view

## New in this version

- **5 movies** instead of just 1, each with its own show and 20 seats
- **Live-ish review/chat feed** per movie - polls every 3 seconds so comments from
  other users show up without a manual refresh
- **System Activity panel** on the booking screen - shows locking, transaction
  commit/rollback, and scheduler events live, so the OS/DBMS concepts are actually
  visible while using the app instead of hidden in a terminal

## Setup

1. Install MySQL locally if you don't have it, then run:
   ```
   mysql -u root -p < backend/schema.sql
   ```
   **If you already ran schema.sql before (old 1-movie version)**, don't rerun it -
   it'll wipe your data. Instead run:
   ```
   python seed_more_movies.py
   ```
   after setting up `database.py` (next step) - this safely adds the 4 new movies.
2. Open `backend/database.py` and put in your MySQL password.
3. Install Python packages:
   ```
   cd backend
   pip install -r requirements.txt
   ```
4. Run the backend:
   ```
   python app.py
   ```
5. Open `frontend/index.html` directly in your browser (double-click it,
   no server needed for the frontend).

## How to demo the locking (the important part)

1. Open `frontend/index.html` in two separate browser tabs.
2. In tab 1, set "Booking as" to Test User A. In tab 2, set it to Test User B.
3. Click the SAME seat in both tabs as close together as you can.
4. One tab will book it successfully, the other will get a
   "seat is not available" error - that's the row lock doing its job.

You can also just watch it in the terminal where `app.py` is running -
the scheduler prints a line every time it releases an expired hold.

## How to demo the deadlock (new, strengthens the OS side)

1. Make sure seats 1 and 2 (A1 and A2) are set to 'available' in the DB.
2. Stop `app.py` if it's running, or just make sure nothing else is
   holding those two seats.
3. Run:
   ```
   python deadlock_demo.py
   ```
4. Watch the output - one transaction will commit, the other will show
   MySQL's deadlock error message. That error IS the detection mechanism
   working, not a bug.

## Folder structure

```
cinesync/
├── backend/
│   ├── app.py          - Flask routes: get seats, hold seat, book seat
│   ├── scheduler.py     - background job, frees expired seat holds
│   ├── database.py      - MySQL connection helper
│   ├── schema.sql        - full DB schema + sample data
│   └── requirements.txt
└── frontend/
    ├── index.html
    ├── style.css
    └── script.js
```
