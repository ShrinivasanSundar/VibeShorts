"""Document repositories. Transaction writes are deferred until all reads finish."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from copy import deepcopy
from threading import RLock
from time import perf_counter
from typing import Any

from execution.read_context import cached_read, invalidate_reads
from execution.telemetry import record

Doc = dict[str, Any]
# A top-level field name, or a tuple path into nested maps such as ("members", uid).
Field = str | tuple[str, ...]


def _value(document: Doc, field: Field):
    for key in (field,) if isinstance(field, str) else field:
        document = document.get(key) if isinstance(document, dict) else None
    return document


class GroupQueries:
    def scan_group(self, collection, *, filters=(), order=(("__name__", False),)):
        """Read only eligible work, in bounded batches; cursors avoid starvation."""
        after = None
        while True:
            rows = self.query(collection, filters=filters, order=order, limit=100, after=after, group=True)
            yield from rows
            if len(rows) < 100:
                return
            path, doc = rows[-1]
            after = {field: path if field == "__name__" else doc[field] for field, _ in order}


class UnitOfWork:
    def __init__(self, read: Callable[[str], Doc | None]):
        self.read = read
        self.pending: dict[str, Doc | None] = {}
        self.loaded: dict[str, Doc | None] = {}

    def get(self, path: str) -> Doc | None:
        if path not in self.pending and path not in self.loaded:
            self.loaded[path] = self.read(path)
        return deepcopy(self.pending[path] if path in self.pending else self.loaded[path])

    def set(self, path: str, document: Doc):
        if path in self.loaded and self.loaded[path] == document:
            self.pending.pop(path, None)
            return
        self.pending[path] = deepcopy(document)

    def delete(self, path: str):
        self.pending[path] = None


class MemoryRepository(GroupQueries):
    """Unit-test double only; never selected by application runtime configuration."""

    def __init__(self):
        self.documents: dict[str, Doc] = {}
        self.lock = RLock()

    def get(self, path: str) -> Doc | None:
        with self.lock:
            return cached_read((id(self), path), lambda: deepcopy(self.documents.get(path)))

    def list(self, collection: str) -> list[Doc]:
        with self.lock:
            return [
                deepcopy(d)
                for p, d in sorted(self.documents.items())
                if p.startswith(collection + "/") and p.count("/") == collection.count("/") + 1
            ]

    def atomic(self, action: Callable):
        with self.lock:
            record("repository.transaction_attempts")
            tx = UnitOfWork(lambda p: deepcopy(self.documents.get(p)))
            result = action(tx)
            for path, document in tx.pending.items():
                if document is None:
                    self.documents.pop(path, None)
                else:
                    self.documents[path] = document
            invalidate_reads(self, tx.pending)
            record("repository.committed_writes", sum(d is not None for d in tx.pending.values()))
            record("repository.committed_deletes", sum(d is None for d in tx.pending.values()))
            return result

    def page(self, collection: str, limit: int, after: str = "") -> list[Doc]:
        return [d for d in self.list(collection) if d["id"] > after][:limit]

    def recent(self, collection: str, limit: int) -> list[Doc]:
        return sorted(self.list(collection), key=lambda d: d.get("created_at", 0), reverse=True)[:limit]

    def tail(self, collection: str, limit: int, before: str = "") -> list[Doc]:
        docs = [d for d in self.list(collection) if not before or d["id"] < before]
        return sorted(docs, key=lambda d: d["id"], reverse=True)[:limit]

    def list_where(self, collection: str, field: Field, values: list) -> list[Doc]:
        return [d for d in self.list(collection) if _value(d, field) in values]

    def get_many(self, paths: list[str]) -> list[Doc | None]:
        return [self.get(p) for p in paths]

    def recent_where(self, collection: str, field: str, value, limit: int) -> list[Doc]:
        docs = [d for d in self.list(collection) if d.get(field) == value]
        return sorted(docs, key=lambda d: d.get("created_at", 0), reverse=True)[:limit]

    def page_where(self, collection: str, field: str, value, limit: int, after: str = "") -> list[Doc]:
        return [d for d in self.page(collection, len(self.documents), after) if d.get(field) == value][:limit]

    def above(self, collection: str, field: str, value, limit: int) -> list[Doc]:
        docs = [d for d in self.list(collection) if d.get(field) is not None and d[field] > value]
        return sorted(docs, key=lambda d: d[field])[:limit]

    def latest(self, collection: str, field: str, limit: int, after: str = "") -> list[Doc]:
        docs = sorted(self.list(collection), key=lambda d: (d[field], d["id"]), reverse=True)
        if after:
            index = next((i for i, d in enumerate(docs) if d["id"] == after), None)
            docs = docs[index + 1 :] if index is not None else []
        return docs[:limit]

    def group_where(self, group: str, field: str, values: list) -> list[tuple[str, Doc]]:
        with self.lock:
            return [
                (p, deepcopy(d))
                for p, d in sorted(self.documents.items())
                if p.startswith("projects/") and p.split("/")[-2] == group and d.get(field) in values
            ]

    def delete_tree(self, path: str):
        """Delete a document and every document nested beneath it."""
        with self.lock:
            for key in [k for k in self.documents if k == path or k.startswith(path + "/")]:
                del self.documents[key]

    def query(self, collection, *, filters=(), order=(), limit=None, after=None, group=False):
        with self.lock:
            rows = [
                (p, deepcopy(d))
                for p, d in self.documents.items()
                if (
                    p.split("/")[-2] == collection
                    if group
                    else p.startswith(collection + "/") and p.count("/") == collection.count("/") + 1
                )
            ]

        def value(path, doc, field):
            if field == "__name__":
                return path if group else path.rsplit("/", 1)[-1]
            keys = field if isinstance(field, tuple) else field.split(".")
            for key in keys:
                if not isinstance(doc, dict) or key not in doc:
                    return None
                doc = doc[key]
            return doc

        for field, op, expected in filters:

            def matches(row, field=field, op=op, expected=expected):
                actual = value(*row, field)
                if op == "==":
                    return actual == expected
                if op == "in":
                    return actual in expected
                if op == "!=":
                    return actual is not None and actual != expected
                if actual is None:
                    return False
                return {
                    "<=": lambda: actual <= expected,
                    ">": lambda: actual > expected,
                    ">=": lambda: actual >= expected,
                    "<": lambda: actual < expected,
                }[op]()

            rows = [r for r in rows if matches(r)]
        for field, descending in reversed(order):
            rows = [r for r in rows if value(*r, field) is not None]
            rows.sort(key=lambda r: value(*r, field), reverse=descending)
        if after:

            def follows(row):
                for field, descending in order:
                    actual, cursor = value(*row, field), after[field]
                    if actual != cursor:
                        return actual < cursor if descending else actual > cursor
                return False

            rows = [r for r in rows if follows(r)]
        if limit is not None:
            rows = rows[:limit]
        return rows if group else [d for _, d in rows]


class FirestoreRepository(GroupQueries):
    def __init__(self, project: str):
        from google.cloud import firestore

        self.client = firestore.Client(project=project)

    def get(self, path: str) -> Doc | None:
        return cached_read((id(self), path), lambda: self._get(path))

    def _get(self, path, transaction=None):
        started = perf_counter()
        record("repository.point_reads")
        try:
            return self.client.document(path).get(transaction=transaction).to_dict()
        finally:
            record("repository.read_latency_ms", round((perf_counter() - started) * 1000))

    def query(self, collection, *, filters=(), order=(), limit=None, after=None, group=False):
        from google.cloud.firestore_v1.base_query import FieldFilter
        from google.cloud.firestore_v1.field_path import FieldPath

        query = self.client.collection_group(collection) if group else self.client.collection(collection)
        for field, op, value in filters:
            field = FieldPath(*field).to_api_repr() if isinstance(field, tuple) else field
            query = query.where(filter=FieldFilter(field, op, value))
        for field, descending in order:
            query = query.order_by(field, direction="DESCENDING" if descending else "ASCENDING")
        if after:
            cursor = dict(after)
            if "__name__" in cursor:
                path = cursor["__name__"] if group else collection + "/" + cursor["__name__"]
                cursor["__name__"] = self.client.document(path)
            query = query.start_after(cursor)
        if limit is not None:
            query = query.limit(limit)
        started = perf_counter()
        record("repository.queries")
        rows = list(query.stream())
        record("repository.query_documents", len(rows))
        record("repository.read_latency_ms", round((perf_counter() - started) * 1000))
        return [(s.reference.path, s.to_dict()) for s in rows] if group else [s.to_dict() for s in rows]

    def list(self, collection: str) -> list[Doc]:
        return self.query(collection)

    def recent(self, collection: str, limit: int) -> list[Doc]:
        return self.query(collection, order=[("created_at", True)], limit=limit)

    def tail(self, collection: str, limit: int, before: str = "") -> list[Doc]:
        # Conversation messages have monotonic sequences. Firestore rejects a
        # descending scan ordered solely by the document key.
        after = None
        if before:
            cursor = self.get(collection + "/" + before)
            if not cursor:
                return []
            after = {"sequence": cursor["sequence"]}
        return self.query(collection, order=[("sequence", True)], limit=limit, after=after)

    def list_where(self, collection: str, field: Field, values: list) -> list[Doc]:
        return self.query(collection, filters=[(field, "in", values)])

    def get_many(self, paths: list[str]) -> list[Doc | None]:
        """One batched round trip; results keep the order of ``paths``."""
        if not paths:
            return []
        found = {
            s.reference.path: s.to_dict()
            for s in self.client.get_all([self.client.document(p) for p in dict.fromkeys(paths)])
        }
        return [found.get(p) for p in paths]

    def recent_where(self, collection: str, field: str, value, limit: int) -> list[Doc]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        query = (
            self.client.collection(collection)
            .where(filter=FieldFilter(field, "==", value))
            .order_by("created_at", direction="DESCENDING")
            .limit(limit)
        )
        return [s.to_dict() for s in query.stream()]

    def page_where(self, collection: str, field: str, value, limit: int, after: str = "") -> list[Doc]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        query = (
            self.client.collection(collection)
            .where(filter=FieldFilter(field, "==", value))
            .order_by("__name__")
            .limit(limit)
        )
        if after:
            query = query.start_after({"__name__": self.client.document(collection + "/" + after)})
        return [s.to_dict() for s in query.stream()]

    def above(self, collection: str, field: str, value, limit: int) -> list[Doc]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        query = (
            self.client.collection(collection)
            .where(filter=FieldFilter(field, ">", value))
            .order_by(field)
            .limit(limit)
        )
        return [s.to_dict() for s in query.stream()]

    def latest(self, collection: str, field: str, limit: int, after: str = "") -> list[Doc]:
        query = (
            self.client.collection(collection)
            .order_by(field, direction="DESCENDING")
            .order_by("__name__", direction="DESCENDING")
            .limit(limit)
        )
        if after:
            cursor = self.client.document(collection + "/" + after).get()
            if not cursor.exists:
                return []
            query = query.start_after(cursor)
        return [s.to_dict() for s in query.stream()]

    def group_where(self, group: str, field: str, values: list) -> list[tuple[str, Doc]]:
        """Project-scoped documents in every ``group`` collection matching ``field in values``."""
        from google.cloud.firestore_v1.base_query import FieldFilter

        query = self.client.collection_group(group).where(filter=FieldFilter(field, "in", values))
        return [
            (s.reference.path, s.to_dict())
            for s in query.stream()
            if s.reference.path.startswith("projects/")
        ]

    def delete_tree(self, path: str):
        """Delete a document and every document nested beneath it."""
        self.client.recursive_delete(self.client.document(path))

    def page(self, collection: str, limit: int, after: str = "") -> list[Doc]:
        return self.query(
            collection, order=[("__name__", False)], limit=limit, after={"__name__": after} if after else None
        )

    def atomic(self, action: Callable):
        from google.api_core.exceptions import Aborted
        from google.cloud import firestore

        # The SDK retries Aborted only at commit; contention can also abort a
        # transactional read, which surfaces raw. Writes are buffered in the
        # UnitOfWork, so rerunning the whole action is safe.
        for attempt in range(5):
            try:
                return self._transact(firestore, action)
            except Aborted:
                if attempt == 4:
                    raise
                time.sleep(0.05 * 2**attempt * (1 + random.random()))

    def _transact(self, firestore, action: Callable):
        @firestore.transactional
        def execute(transaction):
            record("repository.transaction_attempts")
            tx = UnitOfWork(lambda p: self._get(p, transaction))
            result = action(tx)
            for path, document in tx.pending.items():
                reference = self.client.document(path)
                if document is None:
                    transaction.delete(reference)
                else:
                    transaction.set(reference, document)
            return result, tx.pending

        result, paths = execute(self.client.transaction(max_attempts=10))
        invalidate_reads(self, paths)
        record("repository.committed_writes", sum(d is not None for d in paths.values()))
        record("repository.committed_deletes", sum(d is None for d in paths.values()))
        return result
