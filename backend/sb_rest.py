"""Shared PostgREST plumbing for the Supabase-backed collection facades.

* ``split_filter`` turns a Mongo filter into PostgREST params for the parts
  it can express EXACTLY and returns the rest as a residual Mongo filter that
  the caller evaluates in Python (``mongo_compat.match``) on the fetched
  rows. Nothing is silently dropped: before this, unsupported operators were
  skipped (widening results) and unknown columns made PostgREST answer 400,
  which the old facades treated as "fall back to Mongo".
* ``fetch_all`` pages past PostgREST's max-rows cap (1,000 on Supabase).
* ``request`` is a service-role HTTP call; modules that tests monkeypatch
  (``inbox_store._sb_request`` etc.) pass their own requester instead.

Service role only; never logs request bodies.
"""
from __future__ import annotations

import asyncio
import logging
import os
import weakref
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import httpx

logger = logging.getLogger("quantro.sb_rest")

Requester = Callable[..., Awaitable[Optional[httpx.Response]]]

PAGE_SIZE = 1000
MAX_FETCH_ROWS = int(os.environ.get("QUANTRO_SB_MAX_FETCH_ROWS") or 50000)


class SupabaseStoreError(RuntimeError):
    """Supabase is the primary for this store and the call failed.

    Raised instead of silently falling back to Mongo (which the Mongo exit
    removes) or silently dropping a write. server.py maps it to HTTP 503.
    """

    def __init__(self, message: str, *, table: Optional[str] = None, status: Optional[int] = None):
        super().__init__(message)
        self.table = table
        self.status = status


class Impossible(Exception):
    """The filter can never match (e.g. ``$in: []``) — skip the round-trip."""


def supabase_url() -> str:
    return (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")


def service_key() -> str:
    return (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()


def configured() -> bool:
    return bool(supabase_url() and service_key())


def service_headers(prefer: Optional[str] = None) -> Optional[Dict[str, str]]:
    key = service_key()
    if not key:
        return None
    h = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        h["Prefer"] = prefer
    return h


# One pooled client per event loop: keep-alive connections instead of a TLS
# handshake per call (the flow_documents facade sits on every request's auth
# path: user upsert, membership lookup, business profile).
_clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient]" = weakref.WeakKeyDictionary()


def _pooled_client() -> httpx.AsyncClient:
    loop = asyncio.get_running_loop()
    client = _clients.get(loop)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            timeout=20.0,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        )
        _clients[loop] = client
    return client


async def aclose() -> None:
    """Close the current loop's pooled client (app shutdown)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    client = _clients.pop(loop, None)
    if client is not None:
        await client.aclose()


async def request(
    method: str,
    path: str,
    *,
    json: Any = None,
    params: Optional[Dict[str, Any]] = None,
    prefer: Optional[str] = None,
    timeout: float = 20.0,
) -> Optional[httpx.Response]:
    """Service-role PostgREST call. ``None`` = not configured / transport error."""
    headers = service_headers(prefer)
    base = supabase_url()
    if not headers or not base:
        return None
    try:
        client = _pooled_client()
        return await client.request(
            method, f"{base}{path}", headers=headers, json=json, params=params, timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("sb_rest %s %s failed: %s", method, path.split("?")[0], type(exc).__name__)
        return None


def short_error(resp: Optional[httpx.Response], limit: int = 160) -> str:
    """Status + a short error body. Safe to log: PostgREST error bodies carry
    codes/messages, and callers only use this for >= 400 responses."""
    if resp is None:
        return "no response (not configured or transport error)"
    text = ""
    try:
        text = (resp.text or "")[:limit]
    except Exception:  # noqa: BLE001
        pass
    return f"{resp.status_code} {text}"


# ── value formatting ───────────────────────────────────────────────────

def iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    return str(value)


def scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return iso(value) or ""
    return str(value)


def quote(value: Any) -> str:
    """Double-quote a value for ``in.(…)`` lists and logic trees."""
    s = scalar(value)
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool, datetime))


# ── filter translation ────────────────────────────────────────────────

def _translate(col: str, cond: Any, *, json_cols: Set[str]) -> Optional[Tuple[List[Tuple[str, str]], List[str]]]:
    """Return ([(param_col, param_value)], [tree_terms]) or None if not exact."""
    is_json = col in json_cols
    if not (isinstance(cond, dict) and cond and all(str(k).startswith("$") for k in cond)):
        # Plain equality.
        if cond is None:
            return [(col, "is.null")], []
        if is_json or not _is_scalar(cond):
            return None
        return [(col, f"eq.{scalar(cond)}")], []

    params: List[Tuple[str, str]] = []
    terms: List[str] = []
    for op, arg in cond.items():
        if op == "$eq":
            sub = _translate(col, arg, json_cols=json_cols)
            if sub is None:
                return None
            params += sub[0]
            terms += sub[1]
        elif op == "$exists":
            params.append((col, "not.is.null" if arg else "is.null"))
        elif op == "$ne":
            if arg is None:
                params.append((col, "not.is.null"))
            elif isinstance(arg, bool) and not is_json:
                # NOT (col IS TRUE) keeps NULL rows — Mongo `$ne` matches missing.
                params.append((col, f"not.is.{scalar(arg)}"))
            elif _is_scalar(arg) and not is_json:
                terms.append(f"or({col}.is.null,{col}.neq.{quote(arg)})")
            else:
                return None
        elif op in ("$in", "$nin"):
            if not isinstance(arg, (list, tuple, set)) or is_json:
                return None
            vals = list(arg)
            if not all(_is_scalar(v) for v in vals):
                return None
            has_null = any(v is None for v in vals)
            rest = [v for v in vals if v is not None]
            if op == "$in":
                if not vals:
                    raise Impossible()
                inner = f"{col}.in.({','.join(quote(v) for v in rest)})" if rest else None
                if has_null and inner:
                    terms.append(f"or({col}.is.null,{inner})")
                elif has_null:
                    params.append((col, "is.null"))
                else:
                    params.append((col, f"in.({','.join(quote(v) for v in rest)})"))
            else:
                if not vals:
                    continue
                if has_null:
                    params.append((col, "not.is.null"))
                    if rest:
                        params.append((col, f"not.in.({','.join(quote(v) for v in rest)})"))
                else:
                    terms.append(f"or({col}.is.null,{col}.not.in.({','.join(quote(v) for v in rest)}))")
        elif op in ("$gt", "$gte", "$lt", "$lte"):
            if is_json or arg is None or isinstance(arg, bool) or not _is_scalar(arg):
                return None
            params.append((col, f"{op[1:]}.{scalar(arg)}"))
        else:
            return None
    return params, terms


def split_filter(
    query: Optional[Dict[str, Any]],
    columns: Iterable[str],
    *,
    aliases: Optional[Dict[str, str]] = None,
    json_cols: Iterable[str] = (),
) -> Tuple[Dict[str, str], Dict[str, Any]]:
    """Split ``query`` into (PostgREST params, residual Mongo filter).

    Params only carry clauses PostgREST evaluates exactly (column NULL is
    treated as a missing field). Multiple conditions on one column and
    NULL-aware negations go into a single ``and=(…)`` tree.

    Raises ``Impossible`` when the filter can never match.
    """
    cols = set(columns)
    jcols = set(json_cols)
    aliases = aliases or {}
    params: Dict[str, str] = {}
    residual: Dict[str, Any] = {}
    terms: List[str] = []
    for key, cond in (query or {}).items():
        k = str(key)
        if k == "$and" and isinstance(cond, list):
            sub_params, sub_res = {}, {}
            ok = True
            for sub in cond:
                p, r = split_filter(sub, cols, aliases=aliases, json_cols=jcols)
                if r:
                    ok = False
                    break
                for pk, pv in p.items():
                    if pk == "and":
                        terms.append(pv[1:-1])
                    elif pk in params or pk in sub_params:
                        terms.append(f"{pk}.{pv}")
                    else:
                        sub_params[pk] = pv
            if ok:
                params.update(sub_params)
            else:
                residual[k] = cond
            continue
        if k.startswith("$") or "." in k:
            residual[k] = cond
            continue
        col = aliases.get(k, k)
        if col not in cols:
            residual[k] = cond
            continue
        translated = _translate(col, cond, json_cols=jcols)
        if translated is None:
            residual[k] = cond
            continue
        tparams, tterms = translated
        for pcol, pval in tparams:
            if pcol in params:
                terms.append(f"{pcol}.{pval}")
            else:
                params[pcol] = pval
        terms.extend(tterms)
    if terms:
        params["and"] = "(" + ",".join(terms) + ")"
    return params, residual


def order_param(sort_spec: Sequence[Tuple[str, int]], columns: Iterable[str], *, aliases: Optional[Dict[str, str]] = None) -> Optional[str]:
    """PostgREST ``order`` matching Mongo (NULL/missing first when ascending).

    ``None`` when a sort key is not a column (caller sorts in Python).
    """
    cols = set(columns)
    aliases = aliases or {}
    parts: List[str] = []
    for key, direction in sort_spec or []:
        col = aliases.get(key, key)
        if col not in cols or "." in col:
            return None
        parts.append(f"{col}.asc.nullsfirst" if direction >= 0 else f"{col}.desc.nullslast")
    return ",".join(parts) if parts else None


async def fetch_all(
    requester: Requester,
    table: str,
    params: Dict[str, str],
    *,
    order: Optional[str],
    limit: Optional[int] = None,
    offset: int = 0,
    page_size: int = PAGE_SIZE,
    max_rows: int = MAX_FETCH_ROWS,
) -> Optional[List[Dict[str, Any]]]:
    """GET every matching row (paged). ``None`` when a page failed."""
    out: List[Dict[str, Any]] = []
    want = limit if (limit is not None and limit > 0) else None
    pos = max(0, int(offset or 0))
    while True:
        page = page_size if want is None else min(page_size, want - len(out))
        if page <= 0:
            break
        p = dict(params)
        p["limit"] = str(page)
        if pos:
            p["offset"] = str(pos)
        if order:
            p["order"] = order
        resp = await requester("GET", f"/rest/v1/{table}", params=p)
        if resp is None or resp.status_code >= 400:
            if resp is not None:
                logger.warning("sb_rest fetch %s → %s", table, short_error(resp))
            return None
        rows = resp.json() or []
        out.extend(rows)
        pos += len(rows)
        if len(rows) < page:
            break
        if len(out) >= max_rows:
            logger.warning("sb_rest fetch %s hit max_rows=%s — result truncated", table, max_rows)
            break
    return out


async def count_exact(requester: Requester, table: str, params: Dict[str, str]) -> Optional[int]:
    """Exact row count via ``Prefer: count=exact`` (no rows transferred)."""
    p = dict(params)
    p["select"] = "*"
    p["limit"] = "0"
    resp = await requester("GET", f"/rest/v1/{table}", params=p, prefer="count=exact")
    if resp is None or resp.status_code >= 400:
        return None
    headers = getattr(resp, "headers", {}) or {}
    cr = headers.get("content-range") or headers.get("Content-Range") or ""
    if "/" in cr:
        tail = cr.rsplit("/", 1)[-1]
        if tail.isdigit():
            return int(tail)
    return None


def chunked(seq: Sequence[Any], size: int = 100) -> Iterable[Sequence[Any]]:
    for i in range(0, len(seq), size):
        yield seq[i:i + size]
