import json
import logging
from collections import Counter
from threading import Lock

logger = logging.getLogger("vibeshorts")
counts = Counter()
lock = Lock()


def event(name: str, **fields):
    with lock:
        counts[name] += 1
    logger.info(json.dumps({"event": name, **fields}, sort_keys=True))


def metrics() -> dict:
    with lock:
        return dict(counts)


def record(name: str, amount: int = 1):
    """Aggregate physical repository work without logging documents or user data."""
    with lock:
        counts[name] += amount
