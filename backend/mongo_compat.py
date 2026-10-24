"""Mongo-compatible semantics for the Supabase-backed collection facades.

Pure functions, no I/O. The facades (doc_store, inbox_store,
product_domain_store, actions.store, connect_store) push down to PostgREST
whatever a Mongo filter can express exactly, and evaluate the rest here so a
filter PostgREST cannot express never silently widens or narrows a result.

Also used by the Mongo → Supabase backfill (scripts/mongo_to_supabase.py).

What is covered is what this codebase uses (see the operator inventory in
docs/mongo-exit-runbook.md): implicit AND, ``$and/$or/$nor``, ``$eq $ne $gt
$gte $lt $lte $in $nin $exists $regex $not $size $all $elemMatch $type``,
dotted paths through arrays, and the update operators ``$set $unset
$setOnInsert $inc $min $max $push $addToSet $pull $rename $currentDate``.
Anything else raises ``ValueError`` instead of guessing.
"""
from __future__ import annotations

import base64
import copy
import math
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

try:  # pragma: no cover - exercised implicitly
    # One class everywhere: Motor raises pymongo's, the Supabase facades raise
    # the same one, so `except DuplicateKeyError` keeps working on both paths
    # and keeps working once motor/pymongo are removed from requirements.
    from pymongo.errors import DuplicateKeyError  # type: ignore
except Exception:  # noqa: BLE001

    class DuplicateKeyError(Exception):  # type: ignore[no-redef]
        """Raised when an insert collides with a unique key."""


__all__ = [
    "DuplicateKeyError",
    "InsertOneResult",
    "InsertManyResult",
    "UpdateResult",
    "DeleteResult",
    "match",
    "apply_update",
    "seed_from_query",
    "project",
    "normalize_sort",
    "sort_docs",
    "to_json",
    "from_json",
    "new_object_id",
    "is_object_id_hex",
]


# ── results (Motor-shaped) ─────────────────────────────────────────────

class InsertOneResult:
    acknowledged = True

    def __init__(self, inserted_id: Any):
        self.inserted_id = inserted_id


class InsertManyResult:
    acknowledged = True

    def __init__(self, inserted_ids: List[Any]):
        self.inserted_ids = inserted_ids


class UpdateResult:
    acknowledged = True

    def __init__(self, matched_count: int = 0, modified_count: int = 0, upserted_id: Any = None):
        self.matched_count = matched_count
        self.modified_count = modified_count
        self.upserted_id = upserted_id

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"UpdateResult(matched={self.matched_count}, modified={self.modified_count}, "
            f"upserted_id={self.upserted_id!r})"
        )


class DeleteResult:
    acknowledged = True

    def __init__(self, deleted_count: int = 0):
        self.deleted_count = deleted_count


# ── ids ─────────────────────────────────────────────────────────────────

_HEX24 = re.compile(r"^[0-9a-f]{24}$")


def is_object_id_hex(value: Any) -> bool:
    return isinstance(value, str) and bool(_HEX24.match(value))


def new_object_id() -> str:
    """24-hex id, same shape as a Mongo ObjectId so ``serialize_doc`` output
    (``id`` = str(_id)) keeps one format across the cutover."""
    try:
        from bson import ObjectId  # type: ignore

        return str(ObjectId())
    except Exception:  # noqa: BLE001 - pymongo removed
        import os
        import time

        return f"{int(time.time()):08x}{os.urandom(8).hex()}"


# ── value helpers ──────────────────────────────────────────────────────

_MISSING = object()


def _is_object_id(value: Any) -> bool:
    return type(value).__name__ == "ObjectId"


def _norm(value: Any) -> Any:
    """Normalize for comparison: naive datetimes are UTC (Mongo stores UTC)."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if _is_object_id(value):
        return str(value)
    return value


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def _eq(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    a, b = _norm(a), _norm(b)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_eq(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_eq(a[k], b[k]) for k in a)
    try:
        return a == b
    except Exception:  # noqa: BLE001
        return False


def _cmp(a: Any, b: Any) -> Optional[int]:
    """-1/0/1, or None when Mongo would not compare the two types."""
    a, b = _norm(a), _norm(b)
    if a is None or b is None:
        return None
    if _is_number(a) and _is_number(b):
        pass
    elif isinstance(a, datetime) and isinstance(b, datetime):
        pass
    elif isinstance(a, str) and isinstance(b, str):
        pass
    else:
        return None
    try:
        return -1 if a < b else (1 if a > b else 0)
    except Exception:  # noqa: BLE001
        return None


def _resolve(value: Any, parts: Sequence[str]) -> List[Any]:
    """All values at a dotted path, traversing arrays like Mongo does."""
    if not parts:
        return [value]
    head, rest = parts[0], parts[1:]
    if isinstance(value, dict):
        if head in value:
            return _resolve(value[head], rest)
        return [_MISSING]
    if isinstance(value, list):
        out: List[Any] = []
        if head.isdigit():
            idx = int(head)
            if idx < len(value):
                out.extend(_resolve(value[idx], rest))
        for el in value:
            if isinstance(el, (dict, list)):
                out.extend(v for v in _resolve(el, parts) if v is not _MISSING)
        return out or [_MISSING]
    return [_MISSING]


def _flatten(values: Iterable[Any]) -> List[Any]:
    """Candidate scalars: each value plus the elements of array values."""
    out: List[Any] = []
    for v in values:
        if v is _MISSING:
            continue
        out.append(v)
        if isinstance(v, list):
            out.extend(v)
    return out


def _equal_any(values: List[Any], target: Any) -> bool:
    if isinstance(target, re.Pattern):
        return any(isinstance(v, str) and target.search(v) for v in _flatten(values))
    for v in values:
        if v is _MISSING:
            if target is None:
                return True
            continue
        if _eq(v, target):
            return True
        if isinstance(v, list) and any(_eq(e, target) for e in v):
            return True
    return False


def _is_op_dict(cond: Any) -> bool:
    return isinstance(cond, dict) and bool(cond) and all(str(k).startswith("$") for k in cond)


_TYPE_ALIASES = {
    "string": lambda v: isinstance(v, str),
    2: lambda v: isinstance(v, str),
    "bool": lambda v: isinstance(v, bool),
    8: lambda v: isinstance(v, bool),
    "date": lambda v: isinstance(v, datetime),
    9: lambda v: isinstance(v, datetime),
    "null": lambda v: v is None,
    10: lambda v: v is None,
    "array": lambda v: isinstance(v, list),
    4: lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
    3: lambda v: isinstance(v, dict),
    "number": _is_number,
    "int": lambda v: isinstance(v, int) and not isinstance(v, bool),
    16: lambda v: isinstance(v, int) and not isinstance(v, bool),
    "long": lambda v: isinstance(v, int) and not isinstance(v, bool),
    18: lambda v: isinstance(v, int) and not isinstance(v, bool),
    "double": lambda v: isinstance(v, float),
    1: lambda v: isinstance(v, float),
}


def _regex_from(arg: Any, options: str = "") -> re.Pattern:
    if isinstance(arg, re.Pattern):
        return arg
    flags = 0
    for ch in options or "":
        flags |= {"i": re.IGNORECASE, "m": re.MULTILINE, "s": re.DOTALL, "x": re.VERBOSE}.get(ch, 0)
    return re.compile(str(arg), flags)


def _apply_op(values: List[Any], op: str, arg: Any, cond: Dict[str, Any]) -> bool:
    if op == "$eq":
        return _equal_any(values, arg)
    if op == "$ne":
        return not _equal_any(values, arg)
    if op == "$in":
        return any(_equal_any(values, t) for t in (arg or []))
    if op == "$nin":
        return not any(_equal_any(values, t) for t in (arg or []))
    if op in ("$gt", "$gte", "$lt", "$lte"):
        for v in _flatten(values):
            c = _cmp(v, arg)
            if c is None:
                continue
            if (op == "$gt" and c > 0) or (op == "$gte" and c >= 0) or (
                op == "$lt" and c < 0
            ) or (op == "$lte" and c <= 0):
                return True
        return False
    if op == "$exists":
        present = any(v is not _MISSING for v in values)
        return present if arg else not present
    if op == "$regex":
        pattern = _regex_from(arg, cond.get("$options", ""))
        return any(isinstance(v, str) and pattern.search(v) for v in _flatten(values))
    if op == "$options":
        return True
    if op == "$not":
        if _is_op_dict(arg):
            return not _match_field(values, arg)
        return not _equal_any(values, _regex_from(arg) if isinstance(arg, (str, re.Pattern)) else arg)
    if op == "$size":
        return any(isinstance(v, list) and len(v) == arg for v in values)
    if op == "$all":
        return all(_equal_any(values, t) for t in (arg or []))
    if op == "$elemMatch":
        for v in values:
            if not isinstance(v, list):
                continue
            for el in v:
                if _is_op_dict(arg) and not isinstance(el, dict):
                    if _match_field([el], arg):
                        return True
                elif isinstance(el, dict) and match(el, arg):
                    return True
        return False
    if op == "$type":
        types = arg if isinstance(arg, list) else [arg]
        checks = [_TYPE_ALIASES.get(t) for t in types]
        if any(c is None for c in checks):
            raise ValueError(f"unsupported $type {arg!r}")
        return any(any(c(v) for c in checks) for v in values if v is not _MISSING)  # type: ignore[misc]
    raise ValueError(f"unsupported query operator {op}")


def _match_field(values: List[Any], cond: Any) -> bool:
    if _is_op_dict(cond):
        return all(_apply_op(values, op, arg, cond) for op, arg in cond.items())
    return _equal_any(values, cond)


def match(doc: Dict[str, Any], query: Optional[Dict[str, Any]]) -> bool:
    """True when ``doc`` satisfies the Mongo filter ``query``."""
    for key, cond in (query or {}).items():
        if key == "$and":
            if not all(match(doc, q) for q in cond):
                return False
        elif key == "$or":
            if not any(match(doc, q) for q in cond):
                return False
        elif key == "$nor":
            if any(match(doc, q) for q in cond):
                return False
        elif str(key).startswith("$"):
            raise ValueError(f"unsupported top-level operator {key}")
        else:
            if not _match_field(_resolve(doc, str(key).split(".")), cond):
                return False
    return True


# ── updates ────────────────────────────────────────────────────────────

def _set_path(doc: Dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur: Any = doc
    for p in parts[:-1]:
        if isinstance(cur, list) and p.isdigit():
            cur = cur[int(p)]
            continue
        nxt = cur.get(p)
        if not isinstance(nxt, (dict, list)):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    last = parts[-1]
    if isinstance(cur, list) and last.isdigit():
        idx = int(last)
        while len(cur) <= idx:
            cur.append(None)
        cur[idx] = value
    else:
        cur[last] = value


def _get_path(doc: Dict[str, Any], path: str) -> Any:
    cur: Any = doc
    for p in path.split("."):
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        elif isinstance(cur, list) and p.isdigit() and int(p) < len(cur):
            cur = cur[int(p)]
        else:
            return _MISSING
    return cur


def _unset_path(doc: Dict[str, Any], path: str) -> None:
    parts = path.split(".")
    cur: Any = doc
    for p in parts[:-1]:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return
    if isinstance(cur, dict):
        cur.pop(parts[-1], None)


def _each(arg: Any) -> Tuple[List[Any], Dict[str, Any]]:
    if isinstance(arg, dict) and "$each" in arg:
        return list(arg["$each"]), {k: v for k, v in arg.items() if k != "$each"}
    return [arg], {}


def _pull_matches(element: Any, cond: Any) -> bool:
    if _is_op_dict(cond):
        return _match_field([element], cond)
    if isinstance(cond, dict) and isinstance(element, dict):
        return match(element, cond)
    return _eq(element, cond)


def is_operator_update(update: Dict[str, Any]) -> bool:
    return bool(update) and all(str(k).startswith("$") for k in update)


def apply_update(doc: Dict[str, Any], update: Dict[str, Any], *, is_insert: bool = False) -> Dict[str, Any]:
    """Return a new document with ``update`` applied (Mongo semantics)."""
    new = copy.deepcopy(doc)
    if not update:
        return new
    if not is_operator_update(update):
        # Replacement document — keeps _id.
        out = copy.deepcopy(update)
        if "_id" in doc:
            out["_id"] = doc["_id"]
        return out
    for op, fields in update.items():
        if op == "$set":
            for k, v in fields.items():
                _set_path(new, k, copy.deepcopy(v))
        elif op == "$setOnInsert":
            if is_insert:
                for k, v in fields.items():
                    _set_path(new, k, copy.deepcopy(v))
        elif op == "$unset":
            for k in fields:
                _unset_path(new, k)
        elif op == "$inc":
            for k, v in fields.items():
                cur = _get_path(new, k)
                _set_path(new, k, (0 if cur is _MISSING or cur is None else cur) + v)
        elif op in ("$min", "$max"):
            for k, v in fields.items():
                cur = _get_path(new, k)
                if cur is _MISSING or cur is None:
                    _set_path(new, k, v)
                    continue
                c = _cmp(v, cur)
                if c is not None and ((op == "$min" and c < 0) or (op == "$max" and c > 0)):
                    _set_path(new, k, v)
        elif op == "$push":
            for k, v in fields.items():
                items, mods = _each(v)
                cur = _get_path(new, k)
                lst = [] if cur is _MISSING or cur is None else list(cur)
                if not isinstance(cur, (list, type(None))) and cur is not _MISSING:
                    raise ValueError(f"$push on non-array field {k}")
                lst.extend(copy.deepcopy(items))
                if "$slice" in mods:
                    n = int(mods["$slice"])
                    lst = lst[n:] if n < 0 else lst[:n]
                _set_path(new, k, lst)
        elif op == "$addToSet":
            for k, v in fields.items():
                items, _ = _each(v)
                cur = _get_path(new, k)
                lst = [] if cur is _MISSING or cur is None else list(cur)
                for it in items:
                    if not any(_eq(it, e) for e in lst):
                        lst.append(copy.deepcopy(it))
                _set_path(new, k, lst)
        elif op == "$pull":
            for k, cond in fields.items():
                cur = _get_path(new, k)
                if isinstance(cur, list):
                    _set_path(new, k, [e for e in cur if not _pull_matches(e, cond)])
        elif op == "$rename":
            for k, target in fields.items():
                cur = _get_path(new, k)
                if cur is not _MISSING:
                    _unset_path(new, k)
                    _set_path(new, target, cur)
        elif op == "$currentDate":
            for k in fields:
                _set_path(new, k, datetime.now(timezone.utc))
        else:
            raise ValueError(f"unsupported update operator {op}")
    return new


def seed_from_query(query: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Fields an upsert inherits from its filter (equality clauses only)."""
    out: Dict[str, Any] = {}

    def _take(q: Dict[str, Any]) -> None:
        for k, v in (q or {}).items():
            if k == "$and":
                for sub in v:
                    _take(sub)
            elif str(k).startswith("$"):
                continue
            elif _is_op_dict(v):
                if "$eq" in v:
                    _set_path(out, k, copy.deepcopy(v["$eq"]))
            else:
                _set_path(out, k, copy.deepcopy(v))

    _take(query or {})
    return out


def update_touches(update: Dict[str, Any]) -> Tuple[set, bool]:
    """(top-level fields written, simple) — simple means only $set/$unset/
    $setOnInsert on top-level keys, which a plain SQL PATCH can express."""
    fields: set = set()
    simple = is_operator_update(update)
    for op, spec in (update or {}).items():
        if op not in ("$set", "$unset", "$setOnInsert"):
            simple = False
        if isinstance(spec, dict):
            for k in spec:
                fields.add(str(k).split(".")[0])
                if "." in str(k):
                    simple = False
    return fields, simple


# ── projection / sort ──────────────────────────────────────────────────

def project(doc: Optional[Dict[str, Any]], projection: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if doc is None or not projection:
        return doc
    spec = dict(projection)
    keep_id = bool(spec.pop("_id", 1))
    include = [k for k, v in spec.items() if v]
    exclude = [k for k, v in spec.items() if not v]
    if include:
        out: Dict[str, Any] = {}
        for k in include:
            v = _get_path(doc, k)
            if v is not _MISSING:
                _set_path(out, k, v)
        if keep_id and "_id" in doc:
            out["_id"] = doc["_id"]
        return out
    out = dict(doc)
    for k in exclude:
        if "." in k:
            out = copy.deepcopy(out)
            _unset_path(out, k)
        else:
            out.pop(k, None)
    if not keep_id:
        out.pop("_id", None)
    return out


SortSpec = List[Tuple[str, int]]


def normalize_sort(key_or_list: Any, direction: Optional[int] = None) -> SortSpec:
    if key_or_list is None:
        return []
    if isinstance(key_or_list, str):
        return [(key_or_list, int(direction or 1))]
    if isinstance(key_or_list, dict):
        return [(k, int(v)) for k, v in key_or_list.items()]
    out: SortSpec = []
    for item in key_or_list:
        if isinstance(item, (list, tuple)):
            out.append((item[0], int(item[1])))
        else:
            out.append((str(item), 1))
    return out


def _sort_key(value: Any) -> Tuple[int, Any]:
    if value is _MISSING or value is None:
        return (1, 0)
    if isinstance(value, bool):
        return (8, int(value))
    if _is_number(value):
        return (2, float(value))
    if isinstance(value, str):
        return (3, value)
    if isinstance(value, dict):
        return (4, str(sorted(value.items())))
    if isinstance(value, list):
        return (5, str(value))
    if isinstance(value, datetime):
        return (9, _norm(value).timestamp())
    if isinstance(value, date):
        return (9, datetime(value.year, value.month, value.day, tzinfo=timezone.utc).timestamp())
    return (10, str(value))


def sort_docs(docs: List[Dict[str, Any]], spec: SortSpec) -> List[Dict[str, Any]]:
    out = list(docs)
    for key, direction in reversed(spec or []):
        out.sort(key=lambda d: _sort_key(_get_path(d, key)), reverse=direction < 0)
    return out


# ── JSON codec for jsonb storage ───────────────────────────────────────

_MARKERS = ("$date", "$dateOnly", "$oid", "$numberDecimal", "$binary", "$float")


def to_json(value: Any) -> Any:
    """Encode a Mongo document value into JSON that round-trips types."""
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return {"$float": "nan"}
        if math.isinf(value):
            return {"$float": "inf" if value > 0 else "-inf"}
        return value
    if isinstance(value, datetime):
        return {"$date": value.isoformat()}
    if isinstance(value, date):
        return {"$dateOnly": value.isoformat()}
    if _is_object_id(value):
        return {"$oid": str(value)}
    if isinstance(value, Decimal) or type(value).__name__ == "Decimal128":
        return {"$numberDecimal": str(value)}
    if isinstance(value, (bytes, bytearray)):
        return {"$binary": base64.b64encode(bytes(value)).decode()}
    if isinstance(value, dict):
        return {str(k): to_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_json(v) for v in value]
    if hasattr(value, "hex") and type(value).__name__ == "UUID":
        return str(value)
    return str(value)


def from_json(value: Any) -> Any:
    if isinstance(value, list):
        return [from_json(v) for v in value]
    if isinstance(value, dict):
        if len(value) == 1:
            (k, v), = value.items()
            if k in _MARKERS and isinstance(v, str):
                try:
                    if k == "$date":
                        return datetime.fromisoformat(v.replace("Z", "+00:00"))
                    if k == "$dateOnly":
                        return date.fromisoformat(v)
                    if k == "$oid":
                        return v
                    if k == "$numberDecimal":
                        return Decimal(v)
                    if k == "$binary":
                        return base64.b64decode(v)
                    if k == "$float":
                        return float(v)
                except Exception:  # noqa: BLE001
                    return v
        return {k: from_json(v) for k, v in value.items()}
    return value
