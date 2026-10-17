"""Bounded cache of hash-verified immutable bytes, never of access decisions."""

from collections import OrderedDict
from threading import RLock
from time import monotonic


class ContentCache:
    def __init__(self, max_bytes=64 * 1024 * 1024, max_entries=20, ttl=600):
        self.max_bytes, self.max_entries, self.ttl = max_bytes, max_entries, ttl
        self.entries = OrderedDict()
        self.bytes = 0
        self.lock = RLock()

    def load(self, key, fetch):
        with self.lock:
            value = self.entries.get(key)
            if value and value[0] > monotonic():
                self.entries.move_to_end(key)
                return value[1]
            if value:
                self.bytes -= len(self.entries.pop(key)[1])
            # Serialize misses so concurrent previews do not download the same package.
            data = fetch()
            if len(data) <= self.max_bytes:
                self.entries[key] = (monotonic() + self.ttl, data)
                self.bytes += len(data)
                while self.bytes > self.max_bytes or len(self.entries) > self.max_entries:
                    self.bytes -= len(self.entries.popitem(last=False)[1][1])
            return data
