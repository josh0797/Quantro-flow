"""Regression: /api/actions/executions must be registered before /api/actions/{action_id}.

Otherwise FastAPI binds action_id='executions' and the list-history endpoint
returns 404 Action not found.
"""
from pathlib import Path


def test_actions_executions_route_registered_before_action_id_param():
    src = Path(__file__).resolve().parents[1] / "server.py"
    text = src.read_text()
    # Use first occurrence of each decorator path
    list_ex = text.index('@app.get("/api/actions/executions")')
    get_action = text.index('@app.get("/api/actions/{action_id}")')
    assert list_ex < get_action, (
        "/api/actions/executions must appear before /api/actions/{action_id} "
        f"(found executions@{list_ex}, action_id@{get_action})"
    )
