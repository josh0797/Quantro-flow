"""In-memory PostgREST stand-in for storage tests (no network, no Supabase).

Implements the subset Flow's stores use: GET/HEAD/POST/PATCH/DELETE on
``/rest/v1/<table>``; filters ``eq neq gt gte lt lte is in`` (+ ``not.``),
``and=(…)`` / ``or(…)`` logic trees, ``col->>key`` JSON paths; ``select``,
``order`` (``.asc/.desc`` + ``.nullsfirst/.nullslast``), ``limit``/``offset``;
``Prefer`` ``return=representation|minimal``, ``count=exact`` and
``resolution=merge-duplicates|ignore-duplicates`` with ``on_conflict``.

Declared tables are STRICT like PostgREST: an unknown column in a filter,
select or body answers 400, a NULL into a NOT NULL column answers 400, a
unique violation 409, and ``on_conflict`` must name a declared unique key
(else 400 / 42P10 — the live bug the migration fixes). Undeclared tables are
lenient (empty 200s) so unrelated Supabase calls in route tests are inert.
"""
from __future__ import annotations

import copy
import json as _json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from urllib.parse import parse_qsl, urlsplit

import storage_flags  # noqa: F401  (import side-effect free; keeps path setup honest)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TableSpec:
    def __init__(
        self,
        columns: Sequence[str],
        *,
        pk: Sequence[str] = ("id",),
        uniques: Sequence[Sequence[str]] = (),
        partial_uniques: Sequence[Sequence[str]] = (),
        not_null: Sequence[str] = (),
        defaults: Optional[Dict[str, Any]] = None,
        auto_uuid_id: bool = True,
    ):
        self.columns = set(columns)
        self.pk = tuple(pk)
        # Full unique keys can arbitrate ON CONFLICT; partial ones only
        # reject duplicates (NULLs distinct in both).
        self.uniques = [tuple(u) for u in uniques] + [self.pk]
        self.partial_uniques = [tuple(u) for u in partial_uniques]
        self.not_null = set(not_null)
        self.defaults = dict(defaults or {})
        self.auto_uuid_id = auto_uuid_id and "id" in self.columns


def _std(extra_cols: Sequence[str], **kw: Any) -> TableSpec:
    cols = {"id", "created_at", "updated_at", *extra_cols}
    defaults = {"created_at": _now, "updated_at": _now}
    defaults.update(kw.pop("defaults", {}))
    not_null = {"created_at", "updated_at", *kw.pop("not_null", ())}
    return TableSpec(sorted(cols), defaults=defaults, not_null=sorted(not_null), **kw)


def flow_tables() -> Dict[str, TableSpec]:
    """Mirror of konta 20260918210000 + 20261026090500 + 20261026090600 (Flow tables)."""
    import inbox_store
    import product_domain_store as pds
    from actions import store as actions_store

    def product(cfg, key: str, extra_not_null: Sequence[str] = ()) -> TableSpec:
        return _std(
            sorted(cfg.known_cols),
            uniques=[("workspace_id", key)],
            not_null=["workspace_id", key, "is_simulation", "hidden_by_real", "extra", *extra_not_null],
            defaults={"is_simulation": False, "hidden_by_real": False, "is_default": False, "extra": dict},
        )

    tables = {
        "flow_documents": TableSpec(
            ["collection", "doc_id", "workspace_id", "doc", "created_at", "updated_at"],
            pk=("collection", "doc_id"),
            not_null=["collection", "doc_id", "doc", "created_at", "updated_at"],
            defaults={"doc": dict, "created_at": _now, "updated_at": _now},
            auto_uuid_id=False,
        ),
        "flow_sync_locks": TableSpec(
            ["lock_key", "provider", "workspace_id", "owner_id", "locked_at", "expires_at", "created_at", "updated_at"],
            pk=("lock_key",),
            not_null=["lock_key", "provider", "workspace_id", "locked_at", "expires_at"],
            defaults={"locked_at": _now, "created_at": _now, "updated_at": _now},
            auto_uuid_id=False,
        ),
        "inbox_items": _std(
            sorted(inbox_store._KNOWN_COLS),
            uniques=[("workspace_id", "inbox_id"), ("workspace_id", "gmail_id"), ("workspace_id", "ms_id")],
            not_null=["inbox_id", "workspace_id", "read", "extra"],
            defaults={"read": False, "extra": dict},
        ),
        "calendar_events": _std(
            sorted(pds.CALENDAR_CFG.known_cols),
            uniques=[("workspace_id", "event_id"), ("workspace_id", "external_provider", "external_event_id")],
            not_null=["workspace_id", "event_id", "is_simulation", "hidden_by_real", "extra"],
            defaults={"is_simulation": False, "hidden_by_real": False, "extra": dict},
        ),
        "contacts": product(pds.CONTACTS_CFG, "contact_id"),
        "activity_events": product(pds.ACTIVITY_CFG, "event_id"),
        "content_items": product(pds.CONTENT_ITEMS_CFG, "content_id"),
        "content_templates": product(pds.CONTENT_TEMPLATES_CFG, "template_id", ["is_default"]),
        "integrations_config": _std(
            ["workspace_id", "provider", "category", "display_name", "status", "last_sync_at",
             "config", "integration_id", "secrets_enc", "extra"],
            uniques=[("workspace_id", "provider")],
            not_null=["workspace_id", "provider", "config", "secrets_enc", "extra"],
            defaults={"config": dict, "secrets_enc": dict, "extra": dict},
        ),
        "provider_connections": _std(
            ["org_id", "workspace_id", "provider", "account_email", "account_name", "provider_user_id",
             "user_id", "scopes", "access_token_enc", "refresh_token_enc", "expires_at", "connected",
             "status", "reauthorization_required", "missing_scopes", "connected_at", "last_sync_at",
             "last_sync_attempt_at", "auto_sync_paused", "last_sync_error", "api_key_enc",
             "connection_id", "environment", "organization_id", "legal_name", "is_production_ready",
             "timezone", "webhook_id", "webhook_token_enc", "webhook_secret_enc", "meta"],
            uniques=[("workspace_id", "provider")],
            not_null=["workspace_id", "provider", "scopes", "connected", "reauthorization_required",
                      "missing_scopes", "auto_sync_paused", "meta"],
            defaults={"scopes": list, "missing_scopes": list, "connected": False,
                      "reauthorization_required": False, "auto_sync_paused": False, "meta": dict},
        ),
        "oauth_states": TableSpec(
            ["state", "provider", "user_id", "workspace_id", "return_to", "redirect_uri",
             "code_verifier", "requested_scopes", "created_at", "expires_at"],
            pk=("state",), not_null=["state", "provider", "expires_at"],
            defaults={"created_at": _now}, auto_uuid_id=False,
        ),
        "webhook_events": TableSpec(
            ["id", "workspace_id", "provider", "connection_id", "event_id", "event_type", "payload",
             "headers_meta", "received_at", "processed_at", "status", "error"],
            partial_uniques=[("provider", "event_id")],
            not_null=["workspace_id", "provider", "payload", "headers_meta", "received_at"],
            defaults={"payload": dict, "headers_meta": dict, "received_at": _now},
        ),
        "action_executions": _std(
            sorted(actions_store.EXEC_COLUMNS),
            uniques=[("execution_id",)],
            partial_uniques=[("workspace_id", "action_id", "idempotency_key")],
            not_null=["execution_id", "workspace_id", "action_id", "status", "input", "result_metadata", "extra"],
            defaults={"input": dict, "result_metadata": dict, "extra": dict},
        ),
        "automation_policies": _std(
            sorted(actions_store.POLICY_COLUMNS),
            uniques=[("policy_id",)],
            not_null=["policy_id", "workspace_id", "enabled", "extra"],
            defaults={"enabled": True, "extra": dict},
        ),
        "action_policies": _std(
            sorted(actions_store.ACTION_POLICY_COLUMNS),
            uniques=[("workspace_id", "action_id")],
            not_null=["workspace_id", "action_id", "auto_approve", "extra"],
            defaults={"auto_approve": False, "extra": dict},
        ),
    }
    return tables


class FakeResponse:
    def __init__(self, status_code: int, body: Any = None, headers: Optional[Dict[str, str]] = None):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}
        self.text = "" if body is None else _json.dumps(body, default=str)

    def json(self) -> Any:
        return self._body


# ── filter parsing ─────────────────────────────────────────────────────

def _split_top(s: str) -> List[str]:
    """Split on commas outside parentheses and quotes."""
    out, depth, cur, quoted, esc = [], 0, [], False, False
    for ch in s:
        if esc:
            cur.append(ch)
            esc = False
            continue
        if ch == "\\" and quoted:
            cur.append(ch)
            esc = True
            continue
        if ch == '"':
            quoted = not quoted
        elif not quoted and ch == "(":
            depth += 1
        elif not quoted and ch == ")":
            depth -= 1
        if ch == "," and depth == 0 and not quoted:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        out.append("".join(cur))
    return out


def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        return v[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return v


def _get(row: Dict[str, Any], col: str) -> Any:
    if "->>" in col:
        base, key = col.split("->>", 1)
        obj = row.get(base)
        if not isinstance(obj, dict) or key not in obj:
            return None
        v = obj[key]
        if v is None:
            return None
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (dict, list)):
            return _json.dumps(v)
        return str(v)
    return row.get(col)


def _coerce_pair(a: Any, b: str) -> Tuple[Any, Any]:
    if isinstance(a, bool):
        return a, b.lower() == "true"
    if isinstance(a, (int, float)) and not isinstance(a, bool):
        try:
            return a, float(b)
        except ValueError:
            return str(a), b
    if isinstance(a, str):
        try:
            da = datetime.fromisoformat(a.replace("Z", "+00:00"))
            db = datetime.fromisoformat(b.replace("Z", "+00:00"))
            da = da if da.tzinfo else da.replace(tzinfo=timezone.utc)
            db = db if db.tzinfo else db.replace(tzinfo=timezone.utc)
            return da, db
        except ValueError:
            return a, b
    return str(a), b


def _cond(row: Dict[str, Any], col: str, expr: str) -> bool:
    negate = False
    if expr.startswith("not."):
        negate, expr = True, expr[4:]
    op, _, val = expr.partition(".")
    cur = _get(row, col)
    if op == "is":
        target = {"null": None, "true": True, "false": False}[val.lower()]
        res = (cur is None) if target is None else (cur is target)
    elif op == "in":
        inner = val[1:-1] if val.startswith("(") else val
        vals = [_unquote(x) for x in _split_top(inner)] if inner else []
        res = cur is not None and any(_coerce_pair(cur, v)[0] == _coerce_pair(cur, v)[1] for v in vals)
    else:
        v = _unquote(val)
        if cur is None:
            res = False
        else:
            a, b = _coerce_pair(cur, v)
            try:
                res = {"eq": a == b, "neq": a != b, "gt": a > b, "gte": a >= b,
                       "lt": a < b, "lte": a <= b}[op]
            except TypeError:
                res = False
            except KeyError:
                raise ValueError(f"unsupported op {op}")
    return (not res) if negate else res


def _tree(row: Dict[str, Any], expr: str, *, is_or: bool) -> bool:
    results = []
    for term in _split_top(expr):
        term = term.strip()
        if term.startswith("or(") and term.endswith(")"):
            results.append(_tree(row, term[3:-1], is_or=True))
        elif term.startswith("and(") and term.endswith(")"):
            results.append(_tree(row, term[4:-1], is_or=False))
        else:
            m = re.match(r"^([A-Za-z0-9_]+(?:->>[A-Za-z0-9_]+)?)\.(.+)$", term)
            if not m:
                raise ValueError(f"bad term {term}")
            results.append(_cond(row, m.group(1), m.group(2)))
    return any(results) if is_or else all(results)


_RESERVED = {"select", "order", "limit", "offset", "on_conflict", "columns"}


class FakePostgrest:
    def __init__(self, tables: Optional[Dict[str, TableSpec]] = None, *, base_url: str = "https://example.supabase.co"):
        self.specs = tables if tables is not None else flow_tables()
        self.rows: Dict[str, List[Dict[str, Any]]] = {t: [] for t in self.specs}
        self.base_url = base_url.rstrip("/")
        self.calls: List[Tuple[str, str]] = []
        self.missing: Set[str] = set()

    def drop_table(self, name: str) -> None:
        """Simulate a table that does not exist (migration not applied)."""
        self.missing.add(name)
        self.specs.pop(name, None)

    # ── helpers ──
    def table(self, name: str) -> List[Dict[str, Any]]:
        return self.rows.setdefault(name, [])

    def _check_cols(self, spec: TableSpec, cols: Sequence[str]) -> Optional[FakeResponse]:
        for c in cols:
            base = c.split("->>")[0]
            if base not in spec.columns:
                return FakeResponse(400, {"code": "PGRST204", "message": f"Could not find the '{base}' column"})
        return None

    def _filter(self, spec: TableSpec, rows: List[Dict[str, Any]], params: Dict[str, str]) -> Tuple[Optional[FakeResponse], List[Dict[str, Any]]]:
        cols = [k for k in params if k not in _RESERVED and k not in ("and", "or")]
        bad = self._check_cols(spec, cols)
        if bad:
            return bad, []
        out = []
        for r in rows:
            ok = all(_cond(r, c, params[c]) for c in cols)
            if ok and "and" in params:
                ok = _tree(r, params["and"][1:-1], is_or=False)
            if ok and "or" in params:
                ok = _tree(r, params["or"][1:-1], is_or=True)
            if ok:
                out.append(r)
        return None, out

    @staticmethod
    def _order(rows: List[Dict[str, Any]], order: Optional[str]) -> List[Dict[str, Any]]:
        if not order:
            return rows
        out = list(rows)
        for part in reversed(order.split(",")):
            bits = part.split(".")
            col, desc = bits[0], "desc" in bits[1:]
            nulls_first = "nullsfirst" in bits[1:] or ("nullslast" not in bits[1:] and desc)

            def key(r, col=col):
                v = r.get(col)
                if isinstance(v, str):
                    try:
                        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
                        return (1, (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp())
                    except ValueError:
                        return (2, v)
                if isinstance(v, bool):
                    return (0, int(v))
                if isinstance(v, (int, float)):
                    return (0, float(v))
                return (3, str(v))

            present = [r for r in out if r.get(col) is not None]
            missing = [r for r in out if r.get(col) is None]
            present.sort(key=key, reverse=desc)
            out = (missing + present) if nulls_first else (present + missing)
        return out

    @staticmethod
    def _select(rows: List[Dict[str, Any]], select: Optional[str]) -> List[Dict[str, Any]]:
        if not select or select == "*":
            return [copy.deepcopy(r) for r in rows]
        cols = [c.strip() for c in select.split(",") if c.strip()]
        return [{c: copy.deepcopy(r.get(c)) for c in cols} for r in rows]

    def _conflicts(self, spec: TableSpec, row: Dict[str, Any], key: Tuple[str, ...], ignore: Optional[Dict[str, Any]] = None):
        vals = tuple(row.get(c) for c in key)
        if any(v is None for v in vals):
            return None
        for r in self.table_rows(spec):
            if r is ignore:
                continue
            if tuple(r.get(c) for c in key) == vals:
                return r
        return None

    def table_rows(self, spec: TableSpec) -> List[Dict[str, Any]]:
        for name, s in self.specs.items():
            if s is spec:
                return self.rows[name]
        return []

    def _violates(self, spec: TableSpec, row: Dict[str, Any], ignore: Optional[Dict[str, Any]] = None) -> bool:
        return any(self._conflicts(spec, row, k, ignore) is not None for k in spec.uniques + spec.partial_uniques)

    def _complete(self, spec: TableSpec, row: Dict[str, Any]) -> Optional[FakeResponse]:
        for col, default in spec.defaults.items():
            if col not in row and col in spec.columns:
                row[col] = default() if callable(default) else copy.deepcopy(default)
        if spec.auto_uuid_id and not row.get("id"):
            row["id"] = str(uuid.uuid4())
        for c in spec.not_null:
            if row.get(c) is None:
                return FakeResponse(400, {"code": "23502", "message": f'null value in column "{c}" violates not-null constraint'})
        return None

    # ── entry point ──
    async def request(self, method: str, path: str, *, json: Any = None, params: Optional[Dict[str, Any]] = None,
                      prefer: Optional[str] = None, headers: Optional[Dict[str, str]] = None, **_: Any) -> FakeResponse:
        url = urlsplit(path)
        p: Dict[str, str] = dict(parse_qsl(url.query, keep_blank_values=True))
        for k, v in (params or {}).items():
            p[str(k)] = str(v)
        prefer = prefer or (headers or {}).get("Prefer") or ""
        if json is not None:
            # Same serialization httpx does: a datetime (or any non-JSON
            # value) in a request body fails here exactly like in production.
            json = _json.loads(_json.dumps(json))
        route = url.path
        self.calls.append((method, route))
        if route.rstrip("/") == "/rest/v1":
            return FakeResponse(200, {})
        if not route.startswith("/rest/v1/"):
            return FakeResponse(404, {"message": "not found"})
        table = route[len("/rest/v1/"):]
        if table in self.missing:
            return FakeResponse(404, {"code": "PGRST205", "message": f"Could not find the table 'public.{table}' in the schema cache"})
        spec = self.specs.get(table)
        if spec is None:
            # Lenient: unrelated tables (org_members, profiles, …).
            if method in ("GET", "HEAD"):
                return FakeResponse(200, [], {"content-range": "*/0"})
            return FakeResponse(201 if method == "POST" else 200, [] if "representation" in prefer else None)
        try:
            return self._handle(method, table, spec, p, json, prefer)
        except ValueError as exc:
            return FakeResponse(400, {"message": str(exc)})

    def _handle(self, method: str, table: str, spec: TableSpec, p: Dict[str, str], body: Any, prefer: str) -> FakeResponse:
        rows = self.rows[table]
        rep = "return=representation" in prefer
        if method in ("GET", "HEAD"):
            sel = p.get("select")
            if sel and sel != "*":
                bad = self._check_cols(spec, [c.strip() for c in sel.split(",") if c.strip()])
                if bad:
                    return bad
            bad, matched = self._filter(spec, rows, p)
            if bad:
                return bad
            total = len(matched)
            matched = self._order(matched, p.get("order"))
            off = int(p.get("offset") or 0)
            matched = matched[off:]
            if p.get("limit") is not None:
                matched = matched[: int(p["limit"])]
            headers = {"content-range": f"*/{total}"} if "count=exact" in prefer else {}
            return FakeResponse(200, [] if method == "HEAD" else self._select(matched, sel), headers)

        if method == "POST":
            items = body if isinstance(body, list) else [body]
            conflict = tuple(c for c in (p.get("on_conflict") or "").split(",") if c)
            if conflict and conflict not in spec.uniques:
                return FakeResponse(400, {"code": "42P10", "message": "there is no unique or exclusion constraint matching the ON CONFLICT specification"})
            merge = "merge-duplicates" in prefer
            ignore = "ignore-duplicates" in prefer
            out = []
            staged: List[Tuple[str, Dict[str, Any], Optional[Dict[str, Any]]]] = []
            for item in items:
                bad = self._check_cols(spec, list(item))
                if bad:
                    return bad
                existing = self._conflicts(spec, item, conflict) if conflict else None
                if existing is not None:
                    if ignore:
                        continue
                    if merge:
                        staged.append(("update", dict(item), existing))
                        continue
                new = copy.deepcopy(item)
                err = self._complete(spec, new)
                if err:
                    return err
                if self._violates(spec, new):
                    return FakeResponse(409, {"code": "23505", "message": "duplicate key value violates unique constraint"})
                staged.append(("insert", new, None))
            for kind, row, existing in staged:
                if kind == "insert":
                    rows.append(row)
                    out.append(row)
                else:
                    candidate = {**existing, **row}
                    if "updated_at" in spec.columns and "updated_at" not in row:
                        candidate["updated_at"] = _now()
                    if self._violates(spec, candidate, ignore=existing):
                        return FakeResponse(409, {"code": "23505", "message": "duplicate key value"})
                    existing.update(candidate)
                    out.append(existing)
            return FakeResponse(201, self._select(out, p.get("select")) if rep else None)

        if method == "PATCH":
            bad = self._check_cols(spec, list(body or {}))
            if bad:
                return bad
            bad, matched = self._filter(spec, rows, p)
            if bad:
                return bad
            for r in matched:
                candidate = {**r, **copy.deepcopy(body or {})}
                if "updated_at" in spec.columns:
                    candidate["updated_at"] = _now()
                for c in spec.not_null:
                    if candidate.get(c) is None:
                        return FakeResponse(400, {"code": "23502", "message": f'null value in column "{c}"'})
                if self._violates(spec, candidate, ignore=r):
                    return FakeResponse(409, {"code": "23505", "message": "duplicate key value"})
                r.update(candidate)
            return FakeResponse(200, self._select(matched, p.get("select")) if rep else None)

        if method == "DELETE":
            bad, matched = self._filter(spec, rows, p)
            if bad:
                return bad
            ids = {id(r) for r in matched}
            self.rows[table] = [r for r in rows if id(r) not in ids]
            return FakeResponse(200, self._select(matched, p.get("select")) if rep else None)

        return FakeResponse(405, {"message": method})

    # ── httpx.AsyncClient stand-in ──
    def async_client_factory(self, real_async_client: Any):
        emulator = self

        class _Client:
            def __init__(self, *args: Any, **kwargs: Any):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc: Any):
                return False

            async def aclose(self):
                return None

            async def request(self, method: str, url: str, **kwargs: Any):
                return await emulator.handle_url(method, url, **kwargs)

            async def get(self, url: str, **kwargs: Any):
                return await self.request("GET", url, **kwargs)

            async def head(self, url: str, **kwargs: Any):
                return await self.request("HEAD", url, **kwargs)

            async def post(self, url: str, **kwargs: Any):
                return await self.request("POST", url, **kwargs)

            async def patch(self, url: str, **kwargs: Any):
                return await self.request("PATCH", url, **kwargs)

            async def delete(self, url: str, **kwargs: Any):
                return await self.request("DELETE", url, **kwargs)

        def factory(*args: Any, **kwargs: Any):
            if "transport" in kwargs:
                return real_async_client(*args, **kwargs)
            return _Client()

        return factory

    async def handle_url(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        import httpx

        if not url.startswith(self.base_url):
            raise httpx.ConnectError(f"network disabled in tests: {urlsplit(url).netloc}")
        headers = kwargs.get("headers") or {}
        return await self.request(
            method, url[len(self.base_url):],
            json=kwargs.get("json"), params=kwargs.get("params"),
            prefer=headers.get("Prefer"),
        )
