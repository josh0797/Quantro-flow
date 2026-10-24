import { apiErrorMessage } from './apiError';

/**
 * Error codes the Flow API answers when Quantro OS People OS refuses (or Flow
 * cannot run) a team change: invites, acceptances, role changes, removals.
 * Kept in lock-step with backend/people_os.py ERRORS (checked by
 * backend/tests/test_people_os_membership.py); each one needs Spanish and
 * English copy under `people_os.errors` in src/i18n/translations.js.
 */
export const PEOPLE_OS_ERROR_CODES = [
  'seat_required',
  'plan_required',
  'permission_required',
  'role_not_grantable',
  'owner_managed',
  'self_change',
  'self_leave_unavailable',
  'not_member',
  'duplicate_invite',
  'invalid_email',
  'invalid_input',
  'member_not_found',
  'people_os_unavailable',
  'people_os_failed',
  'ownership_transfer_disabled',
  'owner_change_disabled',
  'email_required',
  'legacy_invite_read_only',
  'invite_already_accepted',
  'invite_invalid',
  'invite_expired',
  'invite_used',
  'invite_revoked',
  'email_mismatch',
  'email_unconfirmed',
  'auth_required',
  'rate_limited',
];

/** People keys the API may name in `permission_required` (people.<name>). */
export const PEOPLE_PERMISSION_NAMES = ['view', 'invite', 'change_role', 'manage_access', 'delete'];

/**
 * User-facing text for a failed team call: the translated People OS reason
 * when the API sent one of the codes above (with the Quantro OS function's
 * name for `permission_required`), otherwise the generic API message.
 */
export function peopleOsErrorMessage(err, t) {
  const detail = err?.response?.data?.detail;
  const code = detail && typeof detail === 'object' ? detail.error : null;
  if (!PEOPLE_OS_ERROR_CODES.includes(code)) return apiErrorMessage(err);
  if (code === 'permission_required' && typeof detail.permission === 'string') {
    const name = detail.permission.replace(/^people\./, '');
    if (PEOPLE_PERMISSION_NAMES.includes(name)) {
      return t('people_os.errors.permission_required_named', {
        permission: t(`people_os.permission_names.${name}`),
      });
    }
  }
  return t(`people_os.errors.${code}`);
}
