import threading
import time
from datetime import datetime

from database import get_connection
from activity import log_event

CHECK_INTERVAL_SECONDS = 30


def release_expired_holds():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        
        cursor.execute(
            "SELECT id, seat_no FROM seats WHERE status='held' AND held_until < %s",
            (datetime.now(),)
        )
        expired = cursor.fetchall()

        cursor.execute(
            "UPDATE seats SET status='available', held_by=NULL, held_until=NULL "
            "WHERE status='held' AND held_until < %s",
            (datetime.now(),)
        )
        released = cursor.rowcount
        conn.commit()

        if released > 0:
            print(f"[scheduler] released {released} expired seat hold(s)")
            for seat in expired:
                log_event(f"Scheduler released seat {seat['seat_no']} (hold expired)")

    except Exception as e:
        conn.rollback()
        print(f"[scheduler] error while releasing holds: {e}")
    finally:
        cursor.close()
        conn.close()


def _run_loop():
    while True:
        release_expired_holds()
        time.sleep(CHECK_INTERVAL_SECONDS)


def start_scheduler():
    # daemon=True so this thread doesn't block the app from exiting
    t = threading.Thread(target=_run_loop, daemon=True)
    t.start()
    print("[scheduler] started, checking every", CHECK_INTERVAL_SECONDS, "seconds")
