"""Document repositories. Transaction writes are deferred until all reads finish."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from threading import RLock
from typing import Any

Doc = dict[str, Any]


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


class FirestoreRepository:
    def __init__(self, project: str):
        from google.cloud import firestore

        self.client = firestore.Client(project=project)

    def get(self, path: str) -> Doc | None:
        return self.client.document(path).get().to_dict()

    def list(self, collection: str) -> list[Doc]:
        return [s.to_dict() for s in self.client.collection(collection).stream()]

    def page(self, collection: str, limit: int, after: str = "") -> list[Doc]:
        query = self.client.collection(collection).order_by("__name__").limit(limit)
        if after:
            query = query.start_after({"__name__": self.client.document(collection + "/" + after)})
        return [s.to_dict() for s in query.stream()]

    def atomic(self, action: Callable):
        from google.cloud import firestore

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
