"""Document repositories. Transaction writes are deferred until all reads finish."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from copy import deepcopy
from threading import RLock
from typing import Any

Doc = dict[str, Any]
# A top-level field name, or a tuple path into nested maps such as ("members", uid).
Field = str | tuple[str, ...]


def _value(document: Doc, field: Field):
    for key in (field,) if isinstance(field, str) else field:
        document = document.get(key) if isinstance(document, dict) else None
    return document


class UnitOfWork:
    def __init__(self, read: Callable[[str], Doc | None]):
        self.read = read
        self.pending: dict[str, Doc | None] = {}

    def get(self, path: str) -> Doc | None:
        return deepcopy(self.pending[path] if path in self.pending else self.read(path))

    def set(self, path: str, document: Doc):
        self.pending[path] = deepcopy(document)

    def delete(self, path: str):
        self.pending[path] = None


class MemoryRepository:
    """Unit-test double only; never selected by application runtime configuration."""

    def __init__(self):
        self.documents: dict[str, Doc] = {}
        self.lock = RLock()

    def get(self, path: str) -> Doc | None:
        with self.lock:
            return deepcopy(self.documents.get(path))

    def list(self, collection: str) -> list[Doc]:
        with self.lock:
            return [
                deepcopy(d)
                for p, d in sorted(self.documents.items())
                if p.startswith(collection + "/") and p.count("/") == collection.count("/") + 1
            ]

    def atomic(self, action: Callable):
        with self.lock:
            tx = UnitOfWork(self.get)
            result = action(tx)
            for path, document in tx.pending.items():
                if document is None:
                    self.documents.pop(path, None)
                else:
                    self.documents[path] = document
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


class FirestoreRepository:
    def __init__(self, project: str):
        from google.cloud import firestore

        self.client = firestore.Client(project=project)

    def get(self, path: str) -> Doc | None:
        return self.client.document(path).get().to_dict()

    def list(self, collection: str) -> list[Doc]:
        return [s.to_dict() for s in self.client.collection(collection).stream()]

    def recent(self, collection: str, limit: int) -> list[Doc]:
        query = self.client.collection(collection).order_by("created_at", direction="DESCENDING").limit(limit)
        return [s.to_dict() for s in query.stream()]

    def tail(self, collection: str, limit: int, before: str = "") -> list[Doc]:
        # Conversation messages have monotonic sequences. Firestore rejects a
        # descending scan ordered solely by the document key.
        query = self.client.collection(collection).order_by("sequence", direction="DESCENDING").limit(limit)
        if before:
            cursor = self.client.document(collection + "/" + before).get()
            if not cursor.exists:
                return []
            query = query.start_after(cursor)
        return [s.to_dict() for s in query.stream()]

    def list_where(self, collection: str, field: Field, values: list) -> list[Doc]:
        from google.cloud.firestore_v1.base_query import FieldFilter
        from google.cloud.firestore_v1.field_path import FieldPath

        if not isinstance(field, str):
            field = FieldPath(*field).to_api_repr()
        query = self.client.collection(collection).where(filter=FieldFilter(field, "in", values))
        return [s.to_dict() for s in query.stream()]

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
        query = self.client.collection(collection).order_by("__name__").limit(limit)
        if after:
            query = query.start_after({"__name__": self.client.document(collection + "/" + after)})
        return [s.to_dict() for s in query.stream()]

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
            tx = UnitOfWork(lambda p: self.client.document(p).get(transaction=transaction).to_dict())
            result = action(tx)
            for path, document in tx.pending.items():
                reference = self.client.document(path)
                if document is None:
                    transaction.delete(reference)
                else:
                    transaction.set(reference, document)
            return result

        return execute(self.client.transaction(max_attempts=10))
