"""
Mongo indexes for Quantro Actions. Safe to call on every startup.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("quantro.actions.indexes")

ACTION_EXECUTIONS_IDEMPOTENCY_INDEX = "uniq_workspace_action_idempotency_key"


async def ensure_action_indexes(action_executions_col: Any) -> None:
    """
    Partial unique index:
      (workspace_id, action_id, idempotency_key)
    only when idempotency_key exists and is a string (not null).

    Actions without an idempotency_key are unaffected.
    """
    try:
        await action_executions_col.create_index(
            [("workspace_id", 1), ("action_id", 1), ("idempotency_key", 1)],
            unique=True,
            name=ACTION_EXECUTIONS_IDEMPOTENCY_INDEX,
            partialFilterExpression={
                "idempotency_key": {"$exists": True, "$type": "string"},
            },
        )
        logger.info("Ensured index %s on action_executions", ACTION_EXECUTIONS_IDEMPOTENCY_INDEX)
    except Exception as exc:  # noqa: BLE001
        # Duplicate key on existing conflicting data — do not delete; surface loudly.
        logger.error(
            "Failed to ensure %s: %s. If this is a duplicate-key conflict on "
            "historical rows, resolve manually before enabling concurrent idempotent Actions.",
            ACTION_EXECUTIONS_IDEMPOTENCY_INDEX,
            exc,
        )
        raise
