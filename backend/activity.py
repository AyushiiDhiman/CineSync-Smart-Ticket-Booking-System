"""
Small shared module both app.py and scheduler.py import.

The point of this file: make the OS concepts (locking, scheduling,
group-booking ordering) actually VISIBLE on screen, instead of only
existing in backend terminal logs nobody's looking at during a demo.

Every time a seat gets locked, a group of seats gets locked together,
a transaction commits/rolls back, or the scheduler releases a held
seat, we push a short message here. The frontend polls
/api/activity-log and shows it as a live feed.

Just a small thread-safe list capped at MAX_ENTRIES so it doesn't
grow forever during a long demo session.
"""

import threading
from datetime import datetime

_log = []
_lock = threading.Lock()
MAX_ENTRIES = 80


def log_event(message):
    with _lock:
        _log.append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "message": message
        })
        if len(_log) > MAX_ENTRIES:
            _log.pop(0)


def get_log():
    with _lock:
        return list(reversed(_log))  # newest first
