"""Live inbox/calendar must not surface demo rows retired after Google sync.

Regression for: POST /api/integrations/google/sync sets hidden_by_real=True
on simulation rows, but list endpoints historically only applied
get_mode_filter (workspace + is_simulation). Live mode now also excludes
hidden_by_real=True (missing field = visible).
"""
from __future__ import annotations

from typing import Any, Dict


def _matches_live_filter(doc: Dict[str, Any], workspace_id: str) -> bool:
    """Mirror the Live branch of get_mode_filter without importing server.py."""
    filt = {
        "workspace_id": workspace_id,
        "is_simulation": {"$ne": True},
        "hidden_by_real": {"$ne": True},
    }
    if doc.get("workspace_id") != filt["workspace_id"]:
        return False
    if doc.get("is_simulation") is True:
        return False
    if doc.get("hidden_by_real") is True:
        return False
    return True


def test_live_filter_hides_demo_marked_hidden_by_real():
    ws = "ws_demo"
    # Simulation seed retired after real sync — must not appear in Live.
    assert not _matches_live_filter(
        {"workspace_id": ws, "is_simulation": True, "hidden_by_real": True, "from_name": "Sarah Chen"},
        ws,
    )
    # Defense in depth: even a mis-tagged row with hidden_by_real stays hidden.
    assert not _matches_live_filter(
        {"workspace_id": ws, "is_simulation": False, "hidden_by_real": True},
        ws,
    )


def test_live_filter_shows_real_and_unhidden_rows():
    ws = "ws_demo"
    # Real synced mail (is_simulation False, no hidden flag).
    assert _matches_live_filter(
        {"workspace_id": ws, "is_simulation": False, "is_real": True, "from_name": "Boss"},
        ws,
    )
    # Missing hidden_by_real → visible.
    assert _matches_live_filter(
        {"workspace_id": ws, "is_simulation": False},
        ws,
    )
    # Explicit False → visible.
    assert _matches_live_filter(
        {"workspace_id": ws, "is_simulation": False, "hidden_by_real": False},
        ws,
    )


def test_simulation_rows_without_hidden_still_excluded_by_is_simulation():
    ws = "ws_demo"
    assert not _matches_live_filter(
        {"workspace_id": ws, "is_simulation": True, "from_name": "Sarah Chen"},
        ws,
    )
