import threading
from datetime import datetime

_log = []
_lock = threading.Lock()
MAX_ENTRIES = 60


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
        return list(reversed(_log))  
