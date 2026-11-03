"""
ACID Lab - four small, REAL MySQL experiments, one per letter of ACID.

Each demo runs actual transactions on small dedicated tables (lab_*), so it
never touches your real bookings. Each returns a step-by-step "trace" (what
ran, in what order, at what time) that the frontend draws as a timeline.

Every demo can be run WITH the protection and WITHOUT it, so the difference
is something you can see rather than something you have to take on trust:

    Atomicity    transaction + ROLLBACK        vs  autocommit (no transaction)
    Consistency  UNIQUE / CHECK rules          (the database refuses bad data)
    Isolation    SELECT ... FOR UPDATE         vs  plain SELECT (no lock)
    Durability   COMMIT, read back by a NEW connection, check the log setting

The lab tables are created automatically the first time any demo runs.
"""

import threading
import time
from datetime import datetime

from mysql.connector import Error as MySQLError

from database import get_connection

# lab runs reset the same tables, so only one demo runs at a time
_LAB_LOCK = threading.Lock()

_DDL = [
    """CREATE TABLE IF NOT EXISTS lab_seats (
        id INT PRIMARY KEY,
        label VARCHAR(10) NOT NULL,
        status ENUM('available', 'booked') NOT NULL DEFAULT 'available',
        person VARCHAR(50) DEFAULT NULL
    ) ENGINE=InnoDB""",
    # UNIQUE(seat_id): the database itself refuses a second booking for a seat
    """CREATE TABLE IF NOT EXISTS lab_bookings (
        id INT AUTO_INCREMENT PRIMARY KEY,
        seat_id INT NOT NULL,
        person VARCHAR(50) NOT NULL,
        amount DECIMAL(8,2) NOT NULL,
        UNIQUE KEY uq_lab_seat (seat_id),
        FOREIGN KEY (seat_id) REFERENCES lab_seats(id)
    ) ENGINE=InnoDB""",
    # CHECK: the database itself refuses a negative balance (MySQL 8.0.16+)
    """CREATE TABLE IF NOT EXISTS lab_wallet (
        person VARCHAR(50) PRIMARY KEY,
        balance DECIMAL(8,2) NOT NULL,
        CONSTRAINT chk_lab_balance CHECK (balance >= 0)
    ) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS lab_durable_log (
        id INT AUTO_INCREMENT PRIMARY KEY,
        note VARCHAR(200) NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB""",
]


def ensure_tables():
    conn = get_connection()
    cur = conn.cursor()
    try:
        for ddl in _DDL:
            cur.execute(ddl)
        conn.commit()
    finally:
        cur.close()
        conn.close()


class Trace:
    """Thread-safe, time-stamped list of steps."""

    def __init__(self):
        self.t0 = time.perf_counter()
        self._steps = []
        self._lock = threading.Lock()

    def now(self):
        return time.perf_counter() - self.t0

    def add(self, actor, kind, text, at=None):
        with self._lock:
            self._steps.append({
                "t": round(self.now() if at is None else at, 2),
                "actor": actor, "kind": kind, "text": text,
            })

    def result(self):
        with self._lock:
            return sorted(self._steps, key=lambda s: s["t"])   # stable: ties keep insertion order


class _Crash(Exception):
    """Deliberate 'the server died here' used by the atomicity demo."""


def _reset():
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM lab_bookings")
        cur.execute("DELETE FROM lab_seats")
        cur.executemany("INSERT INTO lab_seats (id, label) VALUES (%s, %s)", [(i, f"L{i}") for i in range(1, 7)])
        cur.execute("DELETE FROM lab_wallet")
        cur.execute("INSERT INTO lab_wallet (person, balance) VALUES ('Priya', 300.00)")
        conn.commit()
    finally:
        cur.close()
        conn.close()


def _read_state():
    """Read through a brand-new connection, so we see only what was really committed."""
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT COUNT(*) AS n FROM lab_bookings")
        bookings = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM lab_seats WHERE status = 'booked'")
        booked = cur.fetchone()["n"]
        cur.execute("SELECT balance FROM lab_wallet WHERE person = 'Priya'")
        w = cur.fetchone()
        conn.commit()
        return {"bookings": bookings, "booked_seats": booked, "wallet": float(w["balance"]) if w else None}
    finally:
        cur.close()
        conn.close()


def _invariants():
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        checks = []
        cur.execute("SELECT COUNT(*) AS n FROM (SELECT seat_id FROM lab_bookings GROUP BY seat_id HAVING COUNT(*) > 1) t")
        checks.append({"rule": "No seat has two bookings", "ok": cur.fetchone()["n"] == 0})
        cur.execute("SELECT COUNT(*) AS n FROM lab_wallet WHERE balance < 0")
        checks.append({"rule": "Wallet balance is never negative", "ok": cur.fetchone()["n"] == 0})
        cur.execute(
            "SELECT COUNT(*) AS n FROM lab_bookings b JOIN lab_seats s ON s.id = b.seat_id WHERE s.status <> 'booked'"
        )
        checks.append({"rule": "Every booking points at a booked seat", "ok": cur.fetchone()["n"] == 0})
        conn.commit()
        return checks
    finally:
        cur.close()
        conn.close()


# ----------------------------------------------------------------------
# A - Atomicity
# ----------------------------------------------------------------------

def run_atomicity(safe=True):
    """Priya books 3 seats; the server 'crashes' after the 2nd."""
    with _LAB_LOCK:
        _reset()
        tr = Trace()
        who = "Priya"
        conn = get_connection()
        cur = conn.cursor()
        try:
            if safe:
                tr.add(who, "sql", "BEGIN   (everything below is ONE transaction)")
            else:
                conn.autocommit = True
                tr.add(who, "info", "autocommit = ON. There is NO transaction: every statement is saved the moment it runs.")

            for n, sid in enumerate([1, 2, 3], start=1):
                cur.execute("INSERT INTO lab_bookings (seat_id, person, amount) VALUES (%s, 'Priya', 250.00)", (sid,))
                tr.add(who, "sql", f"INSERT INTO lab_bookings (seat L{sid}, 'Priya', 250)")
                cur.execute("UPDATE lab_seats SET status = 'booked', person = 'Priya' WHERE id = %s", (sid,))
                tr.add(who, "sql", f"UPDATE lab_seats SET status = 'booked' WHERE id = {sid}")
                if n == 2:
                    tr.add(who, "crash", "The server crashes here: 2 of 3 seats written, the 3rd never happens")
                    raise _Crash()
        except _Crash:
            if safe:
                conn.rollback()
                tr.add(who, "rollback", "ROLLBACK   every change since BEGIN is undone")
            else:
                tr.add(who, "error", "Nothing to roll back: the two seats were already saved for good")
        finally:
            cur.close()
            conn.close()

        state = _read_state()
        if safe:
            ok = state["bookings"] == 0 and state["booked_seats"] == 0
            verdict = {
                "ok": ok, "title": "All or nothing",
                "text": f"A fresh connection sees {state['bookings']} bookings and {state['booked_seats']} booked seats. "
                        "The crash left no half-finished booking behind.",
            }
        else:
            verdict = {
                "ok": False, "title": "A half-finished booking",
                "text": f"{state['bookings']} booking rows and {state['booked_seats']} booked seats survived the crash, "
                        "but Priya wanted 3 seats in one go. With no transaction there was nothing to roll back.",
            }
        return {"steps": tr.result(), "state": state, "verdict": verdict}


# ----------------------------------------------------------------------
# C - Consistency
# ----------------------------------------------------------------------

def run_consistency(scenario="double_booking"):
    """The database refuses changes that would break its own rules."""
    if scenario not in ("double_booking", "overdraft"):
        raise ValueError("unknown scenario")

    with _LAB_LOCK:
        _reset()
        tr = Trace()
        check_enforced = True

        if scenario == "double_booking":
            # Priya books L1 properly
            c1 = get_connection()
            cur = c1.cursor()
            try:
                tr.add("Priya", "sql", "BEGIN")
                cur.execute("INSERT INTO lab_bookings (seat_id, person, amount) VALUES (1, 'Priya', 250.00)")
                tr.add("Priya", "sql", "INSERT INTO lab_bookings (seat L1, 'Priya', 250)")
                cur.execute("UPDATE lab_seats SET status = 'booked', person = 'Priya' WHERE id = 1")
                tr.add("Priya", "sql", "UPDATE lab_seats SET status = 'booked' WHERE id = 1")
                c1.commit()
                tr.add("Priya", "commit", "COMMIT   seat L1 is Priya's")
            finally:
                cur.close()
                c1.close()

            # Rohan tries to book the same seat
            c2 = get_connection()
            cur = c2.cursor()
            try:
                tr.add("Rohan", "sql", "BEGIN")
                tr.add("Rohan", "sql", "INSERT INTO lab_bookings (seat L1, 'Rohan', 250)   -- same seat again")
                try:
                    cur.execute("INSERT INTO lab_bookings (seat_id, person, amount) VALUES (1, 'Rohan', 250.00)")
                    tr.add("Rohan", "error", "The database ACCEPTED a second booking for L1: the UNIQUE rule is missing")
                except MySQLError as e:
                    tr.add("Rohan", "error", f"MySQL refused it (error {e.errno}): {e.msg}")
                c2.rollback()
                tr.add("Rohan", "rollback", "ROLLBACK   the bad write is discarded")
            finally:
                cur.close()
                c2.close()

        else:  # overdraft
            c1 = get_connection()
            cur = c1.cursor()
            try:
                tr.add("Priya", "info", "Priya's wallet holds 300. She tries to buy 2 seats at 250 = 500.")
                tr.add("Priya", "sql", "BEGIN")
                for sid in (1, 2):
                    cur.execute("INSERT INTO lab_bookings (seat_id, person, amount) VALUES (%s, 'Priya', 250.00)", (sid,))
                    tr.add("Priya", "sql", f"INSERT INTO lab_bookings (seat L{sid}, 'Priya', 250)")
                    cur.execute("UPDATE lab_seats SET status = 'booked', person = 'Priya' WHERE id = %s", (sid,))
                    tr.add("Priya", "sql", f"UPDATE lab_seats SET status = 'booked' WHERE id = {sid}")
                tr.add("Priya", "sql", "UPDATE lab_wallet SET balance = balance - 500 WHERE person = 'Priya'")
                try:
                    cur.execute("UPDATE lab_wallet SET balance = balance - 500 WHERE person = 'Priya'")
                    check_enforced = False
                    tr.add("Priya", "error", "The database ACCEPTED a negative balance. This MySQL version ignores CHECK "
                                             "rules (they are enforced from MySQL 8.0.16).")
                except MySQLError as e:
                    tr.add("Priya", "error", f"MySQL refused it (error {e.errno}): {e.msg}")
                c1.rollback()
                tr.add("Priya", "rollback", "ROLLBACK   the seats and bookings from this transaction are undone too")
            finally:
                cur.close()
                c1.close()

        state = _read_state()
        rules = _invariants()
        all_ok = all(r["ok"] for r in rules) and check_enforced
        if not check_enforced:
            verdict = {"ok": False, "title": "This MySQL does not enforce CHECK",
                       "text": "The rule was written but ignored. Upgrade to MySQL 8.0.16+ (or MariaDB 10.2+) to see it enforced."}
        else:
            verdict = {"ok": all_ok, "title": "The rules still hold",
                       "text": "The database refused the change that would break its rules, and rolled the transaction back. "
                               "It moved from one valid state to another valid state (or stayed put)."}
        return {"steps": tr.result(), "state": state, "rules": rules, "verdict": verdict}


# ----------------------------------------------------------------------
# I - Isolation
# ----------------------------------------------------------------------

def _safe_worker(tr, name, start_delay, hold_secs, results):
    """Reads the seat WITH a row lock (SELECT ... FOR UPDATE), then books it."""
    time.sleep(start_delay)
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        tr.add(name, "sql", "BEGIN")
        tr.add(name, "lock", "SELECT status FROM lab_seats WHERE id = 1 FOR UPDATE   (asks for the row lock on L1)")
        asked_at = tr.now()
        cur.execute("SELECT status, person FROM lab_seats WHERE id = 1 FOR UPDATE")   # blocks while another txn holds the lock
        row = cur.fetchone()
        waited = tr.now() - asked_at
        if waited > 0.3:
            tr.add(name, "wait", f"...blocked: another transaction holds the lock on L1", at=asked_at + 0.01)
            tr.add(name, "ok", f"Lock acquired after waiting {waited:.1f}s")
        else:
            tr.add(name, "ok", "Lock acquired immediately")

        if row["status"] != "available":
            tr.add(name, "error", f"L1 is already '{row['status']}' (taken by {row['person']}). {name} is turned away.")
            conn.rollback()
            tr.add(name, "rollback", "ROLLBACK   lock released")
            results[name] = "rejected"
            return

        tr.add(name, "info", f"L1 is available. {name} is paying for {hold_secs}s while holding the lock...")
        time.sleep(hold_secs)
        cur.execute("UPDATE lab_seats SET status = 'booked', person = %s WHERE id = 1", (name,))
        tr.add(name, "sql", f"UPDATE lab_seats SET status = 'booked', person = '{name}' WHERE id = 1")
        conn.commit()
        tr.add(name, "commit", "COMMIT   lock released")
        results[name] = "booked"
    except Exception as e:                      # noqa: BLE001 - show any DB problem in the timeline
        tr.add(name, "error", str(e))
        results[name] = "error"
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        cur.close()
        conn.close()


def _unsafe_worker(tr, name, start_delay, think_secs, results):
    """Reads the seat with a plain SELECT (NO lock), thinks, then books it."""
    time.sleep(start_delay)
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        tr.add(name, "sql", "BEGIN")
        tr.add(name, "sql", "SELECT status FROM lab_seats WHERE id = 1   (plain read, NO lock)")
        cur.execute("SELECT status, person FROM lab_seats WHERE id = 1")
        row = cur.fetchone()
        tr.add(name, "ok", f"Sees L1 as '{row['status']}'")
        tr.add(name, "info", f"{name} is paying for {think_secs}s. Nothing stops anyone else meanwhile...")
        time.sleep(think_secs)
        cur.execute("UPDATE lab_seats SET status = 'booked', person = %s WHERE id = 1", (name,))
        tr.add(name, "sql", f"UPDATE lab_seats SET status = 'booked', person = '{name}' WHERE id = 1")
        conn.commit()
        tr.add(name, "commit", f"COMMIT   {name} is told: booked!")
        results[name] = "booked"
    except Exception as e:                      # noqa: BLE001
        tr.add(name, "error", str(e))
        results[name] = "error"
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        cur.close()
        conn.close()


def run_isolation(safe=True):
    """Priya and Rohan both try to book seat L1 at almost the same moment."""
    with _LAB_LOCK:
        _reset()
        tr = Trace()
        results = {}
        if safe:
            jobs = [("Priya", 0.0, 1.5), ("Rohan", 0.3, 0.0)]
            target = _safe_worker
        else:
            jobs = [("Priya", 0.0, 1.0), ("Rohan", 0.3, 1.3)]
            target = _unsafe_worker

        threads = [threading.Thread(target=target, args=(tr, n, d, h, results)) for n, d, h in jobs]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=70)

        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("SELECT status, person FROM lab_seats WHERE id = 1")
            seat = cur.fetchone()
            conn.commit()
        finally:
            cur.close()
            conn.close()

        winners = [n for n, r in results.items() if r == "booked"]
        if safe:
            ok = len(winners) == 1
            verdict = {
                "ok": ok, "title": "Exactly one winner",
                "text": f"{', '.join(winners) or 'Nobody'} got seat L1. The other transaction waited for the row lock, "
                        "then saw the committed result and backed off. They never saw each other's half-done work.",
            }
        else:
            verdict = {
                "ok": len(winners) < 2, "title": "Double booking (a lost update)",
                "text": f"Both were told 'booked', but the database says L1 belongs to {seat['person']}. "
                        "The other booking was silently overwritten: two happy customers, one seat.",
            }
        return {"steps": tr.result(),
                "state": {"seat": "L1", "status": seat["status"], "owner": seat["person"], "outcomes": results},
                "verdict": verdict}


# ----------------------------------------------------------------------
# D - Durability
# ----------------------------------------------------------------------

_FLUSH_MEANING = {
    "1": "the log is flushed to disk at every COMMIT. A committed row survives a MySQL crash or a power cut (the safe default).",
    "2": "the log is written to the OS at every COMMIT but flushed to disk about once a second. It survives a MySQL crash, "
         "but a power cut could lose the last second.",
    "0": "the log is written and flushed about once a second. A crash can lose the last second of commits.",
}


def run_durability():
    """COMMIT a row, then prove a brand-new session can see it."""
    with _LAB_LOCK:
        tr = Trace()
        note = f"Booking CS-LAB written at {datetime.now().strftime('%H:%M:%S')}"

        conn = get_connection()
        cur = conn.cursor()
        try:
            tr.add("Priya", "sql", "BEGIN")
            cur.execute("INSERT INTO lab_durable_log (note) VALUES (%s)", (note,))
            tr.add("Priya", "sql", f"INSERT INTO lab_durable_log (note) VALUES ('{note}')")
            conn.commit()
            tr.add("Priya", "commit", "COMMIT   MySQL promises this row is now permanent")
        finally:
            cur.close()
            conn.close()

        conn2 = get_connection()
        cur2 = conn2.cursor(dictionary=True)
        try:
            cur2.execute("SELECT COUNT(*) AS n FROM lab_durable_log")
            n = cur2.fetchone()["n"]
            cur2.execute("SHOW VARIABLES LIKE 'innodb_flush_log_at_trx_commit'")
            var = cur2.fetchone()
            conn2.commit()
        finally:
            cur2.close()
            conn2.close()

        flush = str(var["Value"]) if var else "?"
        tr.add("New session", "ok", f"A brand-new connection reads it back: {n} committed row(s) in lab_durable_log")
        tr.add("MySQL", "info", f"innodb_flush_log_at_trx_commit = {flush}: "
                                f"{_FLUSH_MEANING.get(flush, 'see the MySQL docs for this setting.')}")
        return {
            "steps": tr.result(),
            "state": {"rows": n, "flush_setting": flush},
            "verdict": {
                "ok": True, "title": "Committed means kept",
                "text": "Now the real test: stop the MySQL service, start it again, and press 'Check after restart'. "
                        "The row will still be there, because commit wrote it to the redo log on disk.",
            },
        }


def check_durability():
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT COUNT(*) AS n FROM lab_durable_log")
        n = cur.fetchone()["n"]
        cur.execute("SELECT id, note, created_at FROM lab_durable_log ORDER BY id DESC LIMIT 5")
        rows = cur.fetchall()
        conn.commit()
    finally:
        cur.close()
        conn.close()
    for r in rows:
        r["created_at"] = r["created_at"].isoformat() if r["created_at"] else None
    return {"count": n, "rows": rows}
