# Team membership through Quantro OS People OS (decision O12)

Since Quantro OS RBAC PR 6 (konta migrations `20261101180000` … `182000`) the
membership of an organization lives in **People OS** (`team_members`). A
trigger mirrors it into `org_members`, the table Flow reads. Browser / JWT
writes to `org_members` and `invitations` are refused, and the service role
must not be used to go around People OS (seats, plan, People keys, audit).

So Flow **reads** membership as before and **changes** it only through the
People OS RPCs, called with the **caller's JWT** (`supabase_admin.call_rpc`
has no service-role path). Quantro OS applies exactly the rules of its own
Mi Equipo → Accesos screen and writes its own audit row (`rbac_audit_log`).

## Which workspaces

| Workspace | Membership | Changes |
|---|---|---|
| Mapped to a Quantro OS organization (`workspaces.org_id`, or the default org) and Supabase configured | Quantro OS People OS | People OS RPCs (below) |
| Flow-only (no `org_id`, or no Supabase in dev) | Flow's own `workspace_members` / `workspace_invites` docs | Flow, as before (shareable `/join/<token>` links) |

`GET /api/workspaces/{id}/members` returns `people_os: true|false` and
`people_os_url` so the UI can say who manages the team.

## Endpoints → RPCs

| Flow endpoint | People OS call (caller's JWT) | Quantro OS checks |
|---|---|---|
| `POST /api/workspaces/{id}/invites` | `invite_member(p_org_id, p_email, p_role, p_full_name, p_job_title, p_department_id => null, p_company_access => [org])` | `people.invite`; only the owner grants Leader / Accountant (D9 for others); seats (`QSEAT`) and plan (`QPLAN`); one live invite per email |
| `GET /api/workspaces/{id}/invites` | read `team_members` (status `invited`) + legacy `invitations` (read-only) | RLS: `people.view` |
| `DELETE /api/workspaces/{id}/invites/{invite_id}` | `revoke_member_access(p_member_id)` on the invited row | `people.manage_access`; legacy `invitations` rows → 409 `legacy_invite_read_only` |
| `GET /api/invites/{token}` | `get_invitation_preview(p_token)` | token-scoped, no ids |
| `POST /api/invites/{token}/accept` | `accept_team_invite(p_token, p_full_name => null)` (kind `team`) or `accept_invitation(p_token)` (kind `org`, legacy) — the **invitee's** JWT | confirmed email = invited email, unused, unexpired, inviter still allowed, seats / plan; never a downgrade |
| `PATCH /api/workspaces/{id}/members/{user_id}` | `change_member_role(p_member_id, p_role)` | `people.change_role`; Leader / Accountant only by the owner; never one's own role |
| `DELETE /api/workspaces/{id}/members/{user_id}` | `revoke_member_access(p_member_id)` (default: access ends, the record stays and can be reactivated in Quantro OS) | `people.manage_access`; never oneself |
| `DELETE /api/workspaces/{id}/members/{user_id}?permanent=true` | `delete_member(p_member_id)` | `people.delete` (Leader default: off) |

The `team_members` id of a person is read with the caller's JWT
(`team_members?auth_user_id=eq.<user>&or=(organization_id.eq.<org>,invited_by_org_id.eq.<org>)`);
RLS returns it to whoever holds `people.view` (the owner always). If the
caller cannot see a row, Flow answers 404 `member_not_found`.

### Accept link

An invitation is single-use, expires in 7 days and is tied to the email.
Flow returns and lists the link the Quantro OS app understands:

```
https://www.quantro.technology/?invite=<token>
```

(`QUANTRO_OS_APP_URL` overrides the origin; only an `https://host[:port]`
value is accepted.) The invitee can also accept it on Flow's
`/join/<token>` page; after acceptance Flow maps the organization to its
workspace (creating one, as at sign-in, when the organization has none —
never the default workspace unless it is the configured default org).

### Ownership

Flow never transfers ownership, demotes or removes the owner, or invites an
owner: `409 ownership_transfer_disabled` / `409 owner_change_disabled`.
Ownership changes happen in Quantro OS or through support. Nobody removes
themselves from an organization workspace (`409 self_leave_unavailable`;
People OS refuses it) — a leader or the owner revokes them.

## Error codes

Every refusal is `{"detail": {"error": <code>, "message": <English fallback>[, "permission": "people.x"]}}`.
The message is written by Flow (`backend/people_os.py ERRORS`), never the
database's text. The frontend translates each code (es / en) in
`frontend/src/lib/peopleOsErrors.js`; a backend test keeps both lists equal.

| Code | HTTP | From |
|---|---|---|
| `seat_required` | 409 | `QSEAT` |
| `plan_required` | 402 | `QPLAN` |
| `permission_required` (+ `permission`) | 403 | `42501` "This needs the people.x permission" |
| `role_not_grantable` | 403 | `42501` only the owner grants that role |
| `owner_managed` | 403 | `42501` row only the owner manages |
| `self_change` / `self_leave_unavailable` | 409 | own role / access / removal |
| `not_member` | 403 | `42501` not a member |
| `duplicate_invite` | 409 | `23505` |
| `invalid_email` / `invalid_input` | 422 | `22023`, `23514` |
| `member_not_found` | 404 | `P0002`, or no visible People OS row |
| `email_required` | 422 | Flow: People OS invitations need an email |
| `invite_invalid` / `invite_expired` / `invite_used` / `invite_revoked` | 404 / 410 | preview status or `invite_result.code` |
| `email_mismatch` / `email_unconfirmed` / `auth_required` | 403 | `invite_result.code` (never 401: that signs the user out) |
| `rate_limited` | 429 | `invite_result.code` / preview |
| `ownership_transfer_disabled` / `owner_change_disabled` | 409 | Flow |
| `legacy_invite_read_only` / `invite_already_accepted` | 409 | Flow |
| `people_os_unavailable` | 503 | no answer, 5xx, `PGRST202` (function not deployed) |
| `people_os_failed` | 502 | anything else |

## Flags and storage

* Membership reads are unchanged: `_membership_for` reads `org_members`
  (service role) when `QUANTRO_DB_PRIMARY=supabase`, Flow's docs otherwise.
* For organization workspaces the People OS call decides; Flow's own docs
  (`workspace_members`, `workspace_invites`, `audit_log`) are written only
  after it succeeded, as a cache (`_local_identity_writes`). Flow's invite
  doc never stores the Quantro OS token.
* Nothing here touches Mongo when the flags say Supabase (covered by the
  Supabase-only fixture with the Mongo tripwire in
  `backend/tests/test_people_os_membership.py`).
* Flow still writes `org_audit_logs` (service role) and
  `people_onboarding_steps` (caller's JWT) — not membership.

## What Quantro OS (konta) must provide

* The RPCs above with `EXECUTE` for `authenticated` (all on main and in
  production: `20261012000000`, `20261101100000`, `20261101180000`).
* `team_members` SELECT for `people.view` holders (`team_members_people_view_read`).
* Owner decision O14 (konta side): the owner on Starter / without a plan
  must always see and revoke / delete their team. Until that ships, such an
  owner gets `plan_required` / `member_not_found` from Flow too.
* `get_invitation_preview` rate-limits per client IP; Flow calls it from its
  server, so all Flow previews share Flow's egress IP bucket (30 per 5 min).
* Once this Flow version is deployed, the planned DB guard that rejects
  `org_members` writes not coming from the mirror or the org-creation owner
  row can be added: Flow no longer writes `org_members` or `invitations`.
* Rule 4 of `org_role_for` (trust `org_members`) and the mirror stay until
  Flow reads `org_role_for` / `org_memberships_for` instead of `org_members`
  (phase 8 of konta `docs/security/org-authorization.md`; not this change).
