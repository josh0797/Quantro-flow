/**
 * Workspace role helpers shared by the Settings → Integrations surfaces.
 * Mirrors backend role_rank()/require_role(): connecting, testing,
 * changing and disconnecting integrations is leader+.
 */
export const ROLE_RANK = { viewer: 1, member: 2, accountant: 3, leader: 4, owner: 5 };

/**
 * Connecting, reconnecting, testing, syncing, granting permissions and
 * disconnecting are leader+ on the backend (require_role("leader")), so
 * lower roles don't get those buttons. An unknown role (workspaces not
 * loaded yet) keeps them — the backend still enforces the rule.
 */
export function canManageConnections(role) {
  if (!role) return true;
  return (ROLE_RANK[role] || 0) >= ROLE_RANK.leader;
}

/** The active workspace entry from AuthContext (is_current, else by id). */
export function currentWorkspaceOf({ workspaces, currentWorkspaceId } = {}) {
  const list = workspaces || [];
  return list.find((w) => w.is_current) || list.find((w) => w.workspace_id === currentWorkspaceId) || null;
}
