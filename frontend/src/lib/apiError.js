/**
 * User-facing text for a failed axios call to the Flow API.
 *
 * FastAPI puts either a string or an object in `detail`. The AI endpoints
 * answer objects with a localized `message` (e.g. ai_blocked, or
 * ai_own_key_error when the workspace's own OpenAI key is invalid, out of
 * quota or can't use the chosen model). Rendering the raw object in a
 * toast would crash React, and dropping it would hide the fix
 * (Settings → Integrations) from the user.
 */
export function apiErrorMessage(err) {
  const detail = err?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail.message === 'string') return detail.message;
  return err?.message;
}
