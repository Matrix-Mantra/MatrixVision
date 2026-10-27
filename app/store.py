"""Per-user daily counters. Nothing else is stored: no images, no documents, no results.

Firestore (same Firebase project as Matrix) keeps counts shared across Cloud Run instances;
the in-memory store is for local runs and tests.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from . import config

# Days roll over at midnight Nepal time (UTC+05:45).
NPT = timezone(timedelta(hours=5, minutes=45))
COLLECTION = "vision_usage"


def today() -> str:
    return datetime.now(NPT).strftime("%Y-%m-%d")


class MemoryStore:
    def __init__(self) -> None:
        self._counts: dict[tuple[str, str, str], int] = {}
        self._lock = threading.Lock()

    def increment(self, uid: str, kind: str, limit: int) -> int | None:
        """Add one use; return the new count, or None (and change nothing) if the limit is reached."""
        key = (uid, kind, today())
        with self._lock:
            n = self._counts.get(key, 0)
            if n >= limit:
                return None
            self._counts[key] = n + 1
            return n + 1

    def refund(self, uid: str, kind: str) -> None:
        key = (uid, kind, today())
        with self._lock:
            if self._counts.get(key, 0) > 0:
                self._counts[key] -= 1


class FirestoreStore:
    def __init__(self) -> None:
        from firebase_admin import firestore

        from .auth import firebase_app

        self._fs = firestore
        self._db = firestore.client(firebase_app())

    def _ref(self, uid: str):
        # One small doc per user per day; expire it with a Firestore TTL policy on "expires_at".
        return self._db.collection(COLLECTION).document(f"{uid}_{today()}")

    def increment(self, uid: str, kind: str, limit: int) -> int | None:
        ref = self._ref(uid)
        fs = self._fs

        @fs.transactional
        def run(tx):
            snap = ref.get(transaction=tx)
            n = int((snap.to_dict() or {}).get(kind, 0)) if snap.exists else 0
            if n >= limit:
                return None
            tx.set(ref, {kind: n + 1, "uid": uid, "day": today(),
                         "expires_at": datetime.now(timezone.utc) + timedelta(days=2)}, merge=True)
            return n + 1

        return run(self._db.transaction())

    def refund(self, uid: str, kind: str) -> None:
        self._ref(uid).set({kind: self._fs.Increment(-1)}, merge=True)


@lru_cache(maxsize=1)
def get_store() -> MemoryStore | FirestoreStore:
    return FirestoreStore() if config.STORE == "firestore" else MemoryStore()
