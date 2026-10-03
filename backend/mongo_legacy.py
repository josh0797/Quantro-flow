"""The only place Flow opens a MongoDB connection (legacy, being retired).

Collections handed to the stores are lazy proxies: no client is created and
no socket is opened until something actually calls a Mongo method. With
every storage flag on Supabase (see storage_flags.py) the app therefore
starts, serves and shuts down without ever connecting to Mongo, even while
``MONGO_URL`` is still configured.

Every real call is recorded. A call from a domain whose flags say "Supabase
only" is a bug: it is logged at ERROR (``mongo access while disabled``) so it
shows up in ``fly logs`` during the cutover, and the no-Mongo test
(tests/test_no_mongo_request_paths.py) fails on it.

Removing motor later = delete this module's client code once
``storage_flags.summary()["mongo_required"]`` has been False in production.
"""
from __future__ import annotations

import logging
import os
import threading
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

import storage_flags

logger = logging.getLogger("quantro.mongo_legacy")

_client: Any = None
_client_lock = threading.Lock()

# (collection, method, domain, allowed)
AccessEvent = Tuple[str, str, Optional[str], bool]
_recent: Deque[AccessEvent] = deque(maxlen=500)
_listeners: List[Callable[[AccessEvent], None]] = []
_disallowed_count = 0


class MongoDisabledError(RuntimeError):
    """Mongo was needed but MONGO_URL is not configured."""


def _mongo_url() -> str:
    return (os.environ.get("MONGO_URL") or "").strip()


def _db_name() -> str:
    return os.environ.get("DB_NAME", "quantro_os")


def _get_client() -> Any:
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is None:
            url = _mongo_url()
            if not url:
                raise MongoDisabledError(
                    "MONGO_URL is not configured but a Mongo code path ran — "
                    "check storage flags (storage_flags.summary())"
                )
            from motor.motor_asyncio import AsyncIOMotorClient  # lazy: motor is optional

            _client = AsyncIOMotorClient(
                url,
                serverSelectionTimeoutMS=int(os.environ.get("MONGO_SERVER_SELECTION_TIMEOUT_MS") or 8000),
            )
    return _client


def client_created() -> bool:
    return _client is not None


def close() -> None:
    global _client
    if _client is not None:
        try:
            _client.close()
        finally:
            _client = None


def add_listener(fn: Callable[[AccessEvent], None]) -> None:
    _listeners.append(fn)


def remove_listener(fn: Callable[[AccessEvent], None]) -> None:
    try:
        _listeners.remove(fn)
    except ValueError:
        pass


def recent_access() -> List[AccessEvent]:
    return list(_recent)


def disallowed_access_count() -> int:
    return _disallowed_count


def _record(collection: str, method: str, domain: Optional[str]) -> None:
    global _disallowed_count
    allowed = True if domain is None else storage_flags.domain_uses_mongo(domain)
    event: AccessEvent = (collection, method, domain, allowed)
    _recent.append(event)
    if not allowed:
        _disallowed_count += 1
        logger.error(
            "mongo access while disabled: %s.%s (domain=%s) — flags say Supabase only",
            collection, method, domain,
        )
    for fn in list(_listeners):
        fn(event)


_METHODS = (
    "find_one", "find", "insert_one", "insert_many", "update_one", "update_many",
    "delete_one", "delete_many", "count_documents", "estimated_document_count",
    "find_one_and_update", "find_one_and_delete", "find_one_and_replace",
    "replace_one", "create_index", "aggregate", "distinct", "bulk_write",
)


class LazyCollection:
    """Motor-collection stand-in that connects on first real call.

    ``domain`` ties the collection to a storage flag domain so a call made
    while that domain is Supabase-only is reported. Explicit methods keep
    ``hasattr(col, "update_many")`` from connecting.
    """

    def __init__(self, name: str, domain: Optional[str] = None):
        self.name = name
        self.domain = domain

    def _real(self, method: str) -> Any:
        _record(self.name, method, self.domain)
        return _get_client()[_db_name()][self.name]

    def __repr__(self) -> str:  # pragma: no cover
        return f"LazyCollection({self.name!r}, domain={self.domain!r})"

    def __getattr__(self, attr: str) -> Any:
        if attr.startswith("__"):
            raise AttributeError(attr)
        return getattr(self._real(attr), attr)


def _make_method(method: str) -> Callable[..., Any]:
    def _call(self: LazyCollection, *args: Any, **kwargs: Any) -> Any:
        return getattr(self._real(method), method)(*args, **kwargs)

    _call.__name__ = method
    return _call


for _m in _METHODS:
    setattr(LazyCollection, _m, _make_method(_m))


class LazyDatabase:
    """``db["name"]`` → LazyCollection. Tracks the domain of each name."""

    def __init__(self, domains: Optional[Dict[str, str]] = None):
        self._domains = dict(domains or {})

    def collection(self, name: str, domain: Optional[str] = None) -> LazyCollection:
        return LazyCollection(name, domain or self._domains.get(name))

    def __getitem__(self, name: str) -> LazyCollection:
        return self.collection(name)


def to_mongo_id(value: Any) -> Any:
    """String ids (Supabase doc ids) → ObjectId when they were one in Mongo."""
    if isinstance(value, str) and len(value) == 24:
        try:
            from bson import ObjectId  # type: ignore

            if ObjectId.is_valid(value):
                return ObjectId(value)
        except Exception:  # noqa: BLE001
            return value
    return value


def mongo_query(query: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Translate ``_id`` string values back to ObjectIds for mirror writes."""
    q = dict(query or {})
    if "_id" in q:
        v = q["_id"]
        if isinstance(v, dict) and "$in" in v:
            q["_id"] = {**v, "$in": [to_mongo_id(x) for x in v["$in"]]}
        else:
            q["_id"] = to_mongo_id(v)
    return q
