"""Caches live for one read operation only; transaction reads always bypass them."""

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from functools import wraps

_cache = ContextVar("read_cache", default=None)


@contextmanager
def read_scope():
    if _cache.get() is not None:
        yield
        return
    token = _cache.set({})
    try:
        yield
    finally:
        _cache.reset(token)


def cached_read(key, read):
    cache = _cache.get()
    if cache is None:
        return read()
    if key not in cache:
        cache[key] = read()
    return deepcopy(cache[key])


def invalidate_reads(repository, paths):
    cache = _cache.get()
    if cache is not None:
        for path in paths:
            cache.pop((id(repository), path), None)


def read_command(method):
    @wraps(method)
    def execute(*args, **kwargs):
        with read_scope():
            return method(*args, **kwargs)

    return execute
