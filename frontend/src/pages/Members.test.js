// Members ↔ Quantro OS People OS (decision O12). In an organization workspace
// the team is managed by Quantro OS: the page says so, never offers the owner
// role or self-removal, removes people by revoking access (or deleting them
// permanently), and shows People OS refusals in the user's language.
jest.mock('sonner', () => ({ toast: { success: jest.fn(), info: jest.fn(), error: jest.fn(), message: jest.fn() } }));
jest.mock('../lib/api', () => ({
  listMembers: jest.fn(),
  updateMemberRole: jest.fn(),
  removeMember: jest.fn(),
  listInvites: jest.fn(),
  createInvite: jest.fn(),
  revokeInvite: jest.fn(),
  getOnboarding: jest.fn(),
  markOnboardingComplete: jest.fn(),
  getAuditLog: jest.fn(),
  exportAuditLog: jest.fn(),
  renameWorkspace: jest.fn(),
}));
const mockAuth = {
  user: { user_id: 'u-leader', email: 'leader@acme.example', name: 'Leader' },
  currentWorkspaceId: 'ws_org',
  workspaces: [{ workspace_id: 'ws_org', name: 'Acme', role: 'leader', is_current: true }],
  refresh: jest.fn(),
};
jest.mock('../contexts/AuthContext', () => ({ useAuth: () => mockAuth }));
jest.mock('../context/LanguageContext', () => {
  // eslint-disable-next-line global-require
  const { translations } = require('../i18n/translations');
  const resolve = (tree, key) => key.split('.').reduce((node, part) => (node == null ? node : node[part]), tree);
  const t = (k, vars) => {
    const v = resolve(translations.es, k);
    if (typeof v !== 'string') return k;
    return v.replace(/\{\{(\w+)\}\}/g, (_, name) => (vars && name in vars ? String(vars[name]) : ''));
  };
  return { useLanguage: () => ({ lang: 'es', t }) };
});

/* eslint-disable import/first */
import React from 'react';
import { toast } from 'sonner';
import Members from './Members';
import { listMembers, listInvites, removeMember, getOnboarding } from '../lib/api';
import { translations } from '../i18n/translations';
import { act } from 'react';
import { render, flush, click, byTestId } from '../test/render';
/* eslint-enable import/first */

const ROSTER = {
  workspace_id: 'ws_org',
  org_id: 'org-1',
  source: 'supabase',
  people_os: true,
  people_os_url: 'https://www.quantro.technology',
  your_role: 'leader',
  members: [
    { user_id: 'u-owner', role: 'owner', email: 'owner@acme.example', name: 'Owner' },
    { user_id: 'u-leader', role: 'leader', email: 'leader@acme.example', name: 'Leader' },
    { user_id: 'u-member', role: 'member', email: 'member@acme.example', name: 'Member' },
  ],
};

let view;

async function mount(roster = ROSTER, invites = []) {
  listMembers.mockResolvedValue(roster);
  listInvites.mockResolvedValue({ invites, source: 'people_os' });
  view = await render(<Members />);
  await flush(5);
}

// Radix tabs switch on mousedown, not click.
async function openTab(name) {
  await act(async () => {
    byTestId(`tab-${name}`).dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0 }));
  });
  await flush(5);
}

const ACCOUNTANT = { user_id: 'u-acct', role: 'accountant', email: 'acct@acme.example', name: 'Acct' };
const asOwner = (roster) => ({ ...roster, your_role: 'owner' });
const LEADER_USER = mockAuth.user;

beforeEach(() => {
  jest.clearAllMocks();
  removeMember.mockResolvedValue({ success: true, source: 'people_os', permanent: false });
});

afterEach(async () => {
  await view?.unmount();
  document.body.innerHTML = '';
  mockAuth.user = LEADER_USER;
});

it('says the team is managed in Quantro OS and links to it', async () => {
  await mount();
  const note = byTestId('people-os-note');
  expect(note.textContent).toContain(translations.es.members.people_os_note);
  expect(note.querySelector('a').getAttribute('href')).toBe('https://www.quantro.technology');
});

it('never offers to edit the owner or to change or remove yourself', async () => {
  await mount();
  expect(byTestId('remove-member-u-owner')).toBeNull();
  expect(byTestId('role-select-u-owner')).toBeNull();
  expect(byTestId('remove-member-u-leader')).toBeNull();   // self
  expect(byTestId('role-select-u-leader')).toBeNull();     // self
  expect(byTestId('remove-member-u-member')).not.toBeNull();
});

it('revokes access by default and deletes only when asked', async () => {
  await mount();
  await click(byTestId('remove-member-u-member'));
  await flush();
  expect(document.body.textContent).toContain(translations.es.members.remove_people_os_confirm);
  await click(byTestId('confirm-revoke-member-btn'));
  await flush();
  expect(removeMember).toHaveBeenLastCalledWith('ws_org', 'u-member', { permanent: false });
  expect(toast.success).toHaveBeenLastCalledWith(translations.es.members.access_revoked);

  removeMember.mockResolvedValue({ success: true, source: 'people_os', permanent: true });
  await click(byTestId('remove-member-u-member'));
  await flush();
  await click(byTestId('confirm-delete-member-btn'));
  await flush();
  expect(removeMember).toHaveBeenLastCalledWith('ws_org', 'u-member', { permanent: true });
  expect(toast.success).toHaveBeenLastCalledWith(translations.es.members.member_deleted);
});

it('shows a People OS refusal in the user language', async () => {
  removeMember.mockRejectedValue({
    message: 'Request failed with status code 403',
    response: { data: { detail: { error: 'owner_managed', message: 'Only the organization owner can manage…' } } },
  });
  await mount();
  await click(byTestId('remove-member-u-member'));
  await flush();
  await click(byTestId('confirm-revoke-member-btn'));
  await flush();
  expect(toast.error).toHaveBeenLastCalledWith(translations.es.people_os.errors.owner_managed);
});

it('keeps the plain remove flow (and leaving) in a Flow-only workspace', async () => {
  await mount({ ...ROSTER, people_os: false, org_id: null, source: 'mongo' });
  expect(byTestId('people-os-note')).toBeNull();
  expect(byTestId('remove-member-u-leader')).not.toBeNull();   // a member may leave
  await click(byTestId('remove-member-u-member'));
  await flush();
  expect(byTestId('confirm-delete-member-btn')).toBeNull();
});

it('lets only the owner manage an Accountant row in Quantro OS (People OS refuses a Leader)', async () => {
  const roster = { ...ROSTER, members: [...ROSTER.members, ACCOUNTANT] };
  await mount(roster);
  expect(byTestId('role-select-u-acct')).toBeNull();
  expect(byTestId('remove-member-u-acct')).toBeNull();
  expect(byTestId('role-select-u-member')).not.toBeNull();   // a Member row stays manageable
  await view.unmount();

  mockAuth.user = { user_id: 'u-owner', email: 'owner@acme.example', name: 'Owner' };
  await mount(asOwner(roster));
  expect(byTestId('role-select-u-acct')).not.toBeNull();
  expect(byTestId('remove-member-u-acct')).not.toBeNull();
  await view.unmount();

  // Flow-only workspace: an Accountant is below Leader, as before.
  mockAuth.user = LEADER_USER;
  await mount({ ...roster, people_os: false, org_id: null, source: 'mongo' });
  expect(byTestId('role-select-u-acct')).not.toBeNull();
});

it('describes the Quantro OS role in the invite dialog of an organization workspace', async () => {
  await mount();
  await openTab('invites');
  await click(byTestId('new-invite-btn'));
  await flush();
  expect(byTestId('invite-role-people-os-hint').textContent).toBe(translations.es.members.invite_role_people_os_hint);
  const trigger = byTestId('invite-role-select').textContent;
  expect(trigger).toContain(translations.es.members.role_member_people_os_desc);
  expect(trigger).not.toContain(translations.es.members.role_member_desc);
  await view.unmount();

  await mount({ ...ROSTER, people_os: false, org_id: null, source: 'mongo' });
  await openTab('invites');
  await click(byTestId('new-invite-btn'));
  await flush();
  expect(byTestId('invite-role-people-os-hint')).toBeNull();
  expect(byTestId('invite-role-select').textContent).toContain(translations.es.members.role_member_desc);
});

it('onboarding copies only that person\u2019s own Quantro OS invitation, and never offers what People OS refuses', async () => {
  const writeText = jest.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
  const card = (user_id, email, role) => ({
    user_id, email, name: user_id, role, status: 'in_progress', progress: { completed: 1, total: 5 }, steps: [],
  });
  getOnboarding.mockResolvedValue({
    workspace_id: 'ws_org',
    members: [card('u-member', 'member@acme.example', 'member'), card('u-new', 'New@Acme.example', 'member'),
      card('u-acct', 'acct@acme.example', 'accountant')],
    summary: { completed_onboarding: 0, total_members: 3 },
  });
  const invites = [
    { invite_id: 'tm-other', email: 'someone.else@acme.example', url: 'https://www.quantro.technology/?invite=other', revoked: false },
    { invite_id: 'tm-new', email: 'new@acme.example', url: 'https://www.quantro.technology/?invite=mine', revoked: false },
  ];
  await mount({ ...ROSTER, members: [...ROSTER.members, ACCOUNTANT] }, invites);
  await openTab('onboarding');

  expect(byTestId('onb-copy-invite-u-member')).toBeNull();   // no invitation of their own
  await click(byTestId('onb-copy-invite-u-new'));
  await flush();
  expect(writeText).toHaveBeenCalledWith('https://www.quantro.technology/?invite=mine');
  expect(writeText).not.toHaveBeenCalledWith('https://www.quantro.technology/?invite=other');

  expect(byTestId('onb-revoke-u-member')).not.toBeNull();
  expect(byTestId('onb-revoke-u-acct')).toBeNull();          // only the owner manages an Accountant
});
