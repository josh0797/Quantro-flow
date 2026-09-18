"""Shared role ranking for Actions RBAC (mirrors server.py ROLE_RANK)."""
from __future__ import annotations

from typing import Optional

ROLE_RANK = {"viewer": 1, "member": 2, "accountant": 3, "leader": 4, "owner": 5}
ROLE_ALIASES = {
    "agent": "viewer", "operator": "member", "manager": "accountant", "admin": "leader",
    "owner": "owner", "viewer": "viewer", "member": "member", "accountant": "accountant", "leader": "leader",
}


def normalize_role(role: Optional[str]) -> str:
    return ROLE_ALIASES.get((role or "").lower().strip(), "viewer")


def role_rank(role: Optional[str]) -> int:
    return ROLE_RANK.get(normalize_role(role), 0)


def role_at_least(actor_role: Optional[str], minimum_role: str) -> bool:
    return role_rank(actor_role) >= role_rank(minimum_role)
