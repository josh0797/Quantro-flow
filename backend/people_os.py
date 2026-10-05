"""Quantro OS People OS: how Flow invites, accepts, changes roles and removes
people (owner decision O12).

Membership of an organization lives in Quantro OS (``team_members``; konta
RBAC PR 6 mirrors it into the ``org_members`` rows Flow reads). Flow never
writes those tables: every change is a People OS RPC called with the
CALLER's JWT (``supabase_admin.call_rpc``), so Quantro OS applies the same
rules as its own Mi Equipo → Accesos screen — People keys (people.invite,
people.change_role, people.manage_access, people.delete), the roles the
caller may grant, seats (QSEAT) and plan (QPLAN) — and writes the audit row.

This module turns the RPC outcomes into Flow's HTTP answers: a stable
``error`` code the frontend translates (es + en), an English fallback
``message`` written here (never the database's text), and an HTTP status.
Ownership never changes in Flow; it is changed in Quantro OS or by support.
"""
from __future__ import annotations

import logging
import os
import re
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, Optional
from urllib.parse import quote

from fastapi import HTTPException

from supabase_admin import RpcResult

logger = logging.getLogger("quantro.people_os")

# Where invitations are accepted and the team is managed. The Quantro OS app
# reads ``?invite=<token>`` (konta src/lib/invitations.ts readPendingInviteToken)
# for both People OS and legacy invitations.
DEFAULT_QUANTRO_OS_APP_URL = "https://www.quantro.technology"


def quantro_os_app_url() -> str:
    raw = (os.environ.get("QUANTRO_OS_APP_URL") or "").strip().rstrip("/")
    return raw if re.fullmatch(r"https://[A-Za-z0-9.-]+(:\d+)?", raw) else DEFAULT_QUANTRO_OS_APP_URL


def invite_url(token: Optional[str]) -> Optional[str]:
    """The accept link the Quantro OS app understands."""
    if not token:
        return None
    return f"{quantro_os_app_url()}/?invite={quote(str(token), safe='')}"


# code → (HTTP status, English fallback). The frontend shows its own es/en
# copy for each code (frontend/src/lib/peopleOsErrors.js); a new code needs
# both translations there.
ERRORS: Dict[str, tuple] = {
    "seat_required": (409, "Every seat on the plan is taken. The owner can add a seat or free one in Quantro OS."),
    "plan_required": (402, "The organization's plan does not include inviting or managing people. The owner can upgrade it in Quantro OS."),
    "permission_required": (403, "Your role does not have the Quantro OS permission this needs; ask the organization owner."),
    "role_not_grantable": (403, "Only the organization owner can grant the Leader and Accountant roles, or a role with permissions you do not have."),
    "owner_managed": (403, "Only the organization owner can manage a Leader, an Accountant, or someone whose role has permissions you do not have."),
    "self_change": (409, "You cannot change your own role or access."),
    "self_leave_unavailable": (409, "You cannot remove yourself. Ask the owner or a Leader to revoke your access in Quantro OS."),
    "not_member": (403, "You are not a member of this organization in Quantro OS."),
    "duplicate_invite": (409, "This person already has an invitation or access in this organization."),
    "invalid_email": (422, "Enter a valid email address."),
    "invalid_input": (422, "Quantro OS rejected these details. Check the role, name and email."),
    "member_not_found": (404, "This person is not on the Quantro OS team list, or you cannot see the team. Manage them in Quantro OS (My Team → Access)."),
    "people_os_unavailable": (503, "Quantro OS did not answer. Try again in a moment."),
    "people_os_failed": (502, "Quantro OS could not complete the change. Try again, or make it in Quantro OS."),
    "ownership_transfer_disabled": (409, "Ownership is not transferred in Flow. The organization owner changes in Quantro OS or through support."),
    "owner_change_disabled": (409, "The owner cannot be removed or have their role changed in Flow. Ownership changes are made in Quantro OS or through support."),
    "email_required": (422, "Quantro OS invitations are tied to an email address. Enter the person's email."),
    "legacy_invite_read_only": (409, "This older invitation cannot be cancelled from Flow; it stops working when it expires."),
    "invite_already_accepted": (409, "This person already joined. Remove them from the Members list instead."),
    "invite_invalid": (404, "This invitation is not valid."),
    "invite_expired": (410, "This invitation has expired. Ask for a new one."),
    "invite_used": (410, "This invitation was already used."),
    "invite_revoked": (410, "This invitation was cancelled or the person who sent it can no longer invite."),
    "email_mismatch": (403, "This invitation was sent to another email address. Sign in with that email to accept it."),
    "email_unconfirmed": (403, "Confirm your email address before accepting the invitation."),
    "auth_required": (403, "Sign in again to continue."),
    "rate_limited": (429, "Too many attempts. Try again in a few minutes."),
}


@dataclass
class PeopleOSError(Exception):
    error: str
    permission: Optional[str] = None

    @property
    def status(self) -> int:
        return ERRORS.get(self.error, ERRORS["people_os_failed"])[0]

    @property
    def message(self) -> str:
        return ERRORS.get(self.error, ERRORS["people_os_failed"])[1]

    def http(self) -> HTTPException:
        detail: Dict[str, Any] = {"error": self.error, "message": self.message}
        if self.permission:
            detail["permission"] = self.permission
        return HTTPException(status_code=self.status, detail=detail)


def http_error(code: str, permission: Optional[str] = None) -> HTTPException:
    return PeopleOSError(code, permission).http()


_PERMISSION_RE = re.compile(r"needs the (people\.[a-z_]+) permission")

# 42501 refusals of the People OS RPCs (konta 20261101100000 / 20261101130000),
# told apart by their fixed message text. Anything else stays "forbidden"-like
# (permission_required without a key).
_FORBIDDEN_PATTERNS = (
    ("can grant the leader and accountant roles", "role_not_grantable"),
    ("reaches a company where you cannot grant it", "role_not_grantable"),
    ("can manage a leader, an accountant", "owner_managed"),
    ("your own", "self_change"),
    ("remove yourself", "self_change"),
    ("not a member of this organization", "not_member"),
    ("nobody assigns the owner role", "ownership_transfer_disabled"),
    ("sign in to manage your team", "auth_required"),
)


def classify(result: RpcResult) -> PeopleOSError:
    """The Flow error for a failed People OS call.

    The specific SQLSTATEs are checked BEFORE the HTTP status buckets:
    PostgREST answers ``P0*`` (e.g. P0002 "Team member not found") with
    HTTP 500 and an anonymous 42501 with 401, so judging by status first
    would turn them into "Quantro OS did not answer" / the wrong reason."""
    code = (result.code or "").upper()
    text = (result.message or "").lower()
    if result.status == 0:
        return PeopleOSError("auth_required" if code == "AUTH_REQUIRED" else "people_os_unavailable")
    if code == "QSEAT":
        return PeopleOSError("seat_required")
    if code == "QPLAN":
        return PeopleOSError("plan_required")
    if code == "42501":
        match = _PERMISSION_RE.search(result.message or "")
        if match:
            return PeopleOSError("permission_required", match.group(1))
        for needle, err in _FORBIDDEN_PATTERNS:
            if needle in text:
                return PeopleOSError(err)
        return PeopleOSError("permission_required")
    if code == "23505":
        return PeopleOSError("duplicate_invite")
    if code == "22023":
        return PeopleOSError("invalid_email" if "email" in text else "invalid_input")
    if code in ("23514", "22P02"):
        return PeopleOSError("invalid_input")
    if code == "P0002":
        return PeopleOSError("member_not_found")
    # PGRST301/PGRST302: expired, invalid or missing JWT (HTTP 401).
    if code in ("PGRST301", "PGRST302") or result.status == 401:
        return PeopleOSError("auth_required")
    if code in ("PGRST202", "NO_RESPONSE") or result.status >= 500:
        return PeopleOSError("people_os_unavailable")
    if result.status == 403:
        return PeopleOSError("permission_required")
    return PeopleOSError("people_os_failed")


def require_ok(fn: str, result: RpcResult) -> Any:
    """``result.data`` of a successful call, else raise the mapped HTTP error."""
    if result.ok:
        return result.data
    err = classify(result)
    logger.info("people_os.%s refused: status=%s error=%s", fn, result.status, err.error)
    raise err.http()


# ── /api/invites/{token}: token shape + per-user throttle ──────────────
# People OS and legacy invitation tokens are uuids; anything else is
# answered "invalid" without calling Quantro OS.
_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def is_invite_token(token: Optional[str]) -> bool:
    return bool(token) and bool(_UUID_RE.fullmatch(str(token)))


# get_invitation_preview is rate-limited by Quantro OS per client IP
# ('invite_preview:<ip>', 30 per 5 min), and every Flow call comes from
# Flow's server — one bucket for all of Flow. Each user may therefore spend
# only a few previews per window here, so nobody can use the bucket up for
# everyone else; accept does not preview at all (accept_team_invite has its
# own per-user limit in Quantro OS). In-process (per worker): a mitigation,
# not a global quota.
INVITE_WINDOW_SECS = 300
INVITE_LIMITS = {"preview": 6, "accept": 10}
_MAX_THROTTLE_KEYS = 10_000


class _Throttle:
    def __init__(self) -> None:
        self._hits: Dict[str, Deque[float]] = {}

    def allow(self, key: str, limit: int, window: float, now: Optional[float] = None) -> bool:
        now = time.monotonic() if now is None else now
        hits = self._hits.get(key)
        if hits is None:
            if len(self._hits) >= _MAX_THROTTLE_KEYS:
                self._prune(now, window)
            hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] >= window:
            hits.popleft()
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True

    def _prune(self, now: float, window: float) -> None:
        for key in [k for k, v in self._hits.items() if not v or now - v[-1] >= window]:
            del self._hits[key]
        if len(self._hits) >= _MAX_THROTTLE_KEYS:
            self._hits.clear()

    def reset(self) -> None:
        self._hits.clear()


invite_throttle = _Throttle()


def throttle_invite(action: str, user_id: str) -> None:
    """Raise 429 ``rate_limited`` when ``user_id`` used up its ``action``
    budget ("preview" or "accept") for the current window."""
    if not invite_throttle.allow(f"{action}:{user_id}", INVITE_LIMITS[action], INVITE_WINDOW_SECS):
        logger.info("people_os.invite throttled: action=%s", action)
        raise http_error("rate_limited")


# invite_result codes (konta 20261012000000) → Flow error codes.
_INVITE_CODES = {
    "invalid": "invite_invalid",
    "expired": "invite_expired",
    "used": "invite_used",
    "revoked": "invite_revoked",
    "email_mismatch": "email_mismatch",
    "email_unconfirmed": "email_unconfirmed",
    "auth_required": "auth_required",
    "rate_limited": "rate_limited",
}


def invite_code_error(code: Optional[str]) -> HTTPException:
    return http_error(_INVITE_CODES.get(code or "", "invite_invalid"))
