// Plan & usage ↔ the workspace's own OpenAI key. When the active workspace
// connected its own key (Settings → Integrations), the AI credits card says
// AI runs on that key (OpenAI bills directly, no Quantro credits used). When
// AI is blocked, "Agregar mi API key" leads to Settings → Integrations.
const mockDb = { profile: null };
jest.mock('../lib/supabaseClient', () => {
  const query = (table) => {
    const result = table === 'profiles'
      ? { data: mockDb.profile, error: null }
      : { data: [], error: null };
    const builder = {
      select: () => builder,
      eq: () => builder,
      maybeSingle: () => Promise.resolve(result),
      then: (resolve, reject) => Promise.resolve(result).then(resolve, reject),
    };
    return builder;
  };
  return { supabase: { from: query, functions: { invoke: jest.fn() } } };
});
jest.mock('../lib/authFetch', () => ({ authFetch: jest.fn() }));
jest.mock('sonner', () => ({ toast: { success: jest.fn(), info: jest.fn(), error: jest.fn() } }));
const mockAuth = {
  user: { user_id: 'user-1', email: 'owner@example.com', name: 'Owner' },
  workspaces: [{ workspace_id: 'ws_a', name: 'A', role: 'owner', is_current: true }],
  logout: jest.fn(),
};
jest.mock('../contexts/AuthContext', () => ({ useAuth: () => mockAuth }));
const mockLang = { current: 'es' };
jest.mock('../context/LanguageContext', () => {
  // eslint-disable-next-line global-require
  const { translations } = require('../i18n/translations');
  const resolve = (tree, key) => key.split('.').reduce((node, part) => (node == null ? node : node[part]), tree);
  const t = (k, vars) => {
    const v = resolve(translations[mockLang.current], k);
    if (typeof v !== 'string') return k;
    return v.replace(/\{\{(\w+)\}\}/g, (_, name) => (vars && name in vars ? String(vars[name]) : ''));
  };
  return { useLanguage: () => ({ lang: mockLang.current, t }) };
});

/* eslint-disable import/first */
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import PlanAndUsage from './PlanAndUsage';
import { authFetch } from '../lib/authFetch';
import { translations } from '../i18n/translations';
import { render, flush, click, byTestId, createNavSpy } from '../test/render';
/* eslint-enable import/first */

const jsonResponse = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });

const PRO_WITH_CREDITS = {
  id: 'user-1', plan: 'pro', subscription_status: 'active',
  ai_credits_total: 10, ai_credits_used: 2, ai_credits_remaining: 8,
};
const USED_UP_PRO = { ...PRO_WITH_CREDITS, ai_credits_used: 10, ai_credits_remaining: 0 };
const ESSENTIAL = { id: 'user-1', plan: 'essential', ai_credits_total: 0, ai_credits_used: 0, ai_credits_remaining: 0 };

let openaiRow;
let view;
let nav;

async function mount() {
  nav = createNavSpy();
  view = await render(
    <MemoryRouter initialEntries={['/plan']}>
      <nav.Probe />
      <PlanAndUsage />
    </MemoryRouter>,
  );
  await flush(5);
}

beforeEach(() => {
  jest.clearAllMocks();
  mockLang.current = 'es';
  openaiRow = { provider: 'openai', status: 'disconnected', config: {} };
  authFetch.mockImplementation(async (url) => {
    if (String(url).endsWith('/api/integrations/openai')) return jsonResponse(openaiRow);
    return jsonResponse({}, 404);
  });
});

afterEach(async () => {
  await view?.unmount();
  view = null;
});

describe.each(['es', 'en'])('own OpenAI key active (%s)', (lang) => {
  beforeEach(() => {
    mockLang.current = lang;
    mockDb.profile = PRO_WITH_CREDITS;
    openaiRow = { provider: 'openai', status: 'connected', config: { has_api_key: true, model: 'gpt-4o' } };
  });

  it('says AI runs on the workspace key and links to manage it', async () => {
    await mount();
    expect(authFetch).toHaveBeenCalledWith(expect.stringMatching(/\/api\/integrations\/openai$/));
    const pu = translations[lang].plan_usage;
    expect(byTestId('credits-source-badge').textContent).toBe(pu.credits_source_user);
    const fallback = byTestId('credits-fallback');
    expect(fallback.textContent).toContain(pu.credits_fallback_user_key.replace('{{model}}', 'gpt-4o'));
    expect(fallback.textContent).toMatch(lang === 'es' ? /no se consumen créditos de Quantro/ : /no Quantro credits are used/);
    expect(byTestId('credits-blocked')).toBeNull();
    await click(byTestId('credits-manage-key-btn'));
    await flush();
    expect(nav.location.pathname).toBe('/settings/integrations');
  });
});

it('unblocks an out-of-credits plan when the workspace has its own key', async () => {
  mockDb.profile = USED_UP_PRO;
  openaiRow = { provider: 'openai', status: 'connected', config: { has_api_key: true, model: 'gpt-4-turbo' } };
  await mount();
  expect(byTestId('credits-blocked')).toBeNull();
  // A legacy model outside the allowlist runs on the default — say so.
  expect(byTestId('credits-fallback').textContent).toContain('gpt-4o-mini');
});

it('ignores a connected row without a stored key', async () => {
  mockDb.profile = USED_UP_PRO;
  openaiRow = { provider: 'openai', status: 'connected', config: { model: 'gpt-4o' } };
  await mount();
  expect(byTestId('credits-fallback')).toBeNull();
  expect(byTestId('credits-blocked')).not.toBeNull();
});

it('reads a failed integrations call as "no own key"', async () => {
  mockDb.profile = PRO_WITH_CREDITS;
  authFetch.mockImplementation(async () => { throw new Error('offline'); });
  await mount();
  expect(byTestId('credits-source-badge').textContent).toBe(translations.es.plan_usage.credits_source_quantro);
});

describe.each([
  ['out of credits', USED_UP_PRO, 'credits_blocked_message'],
  ['plan without credits (Essential)', ESSENTIAL, 'credits_plan_not_included'],
])('blocked: %s', (_label, profile, messageKey) => {
  it.each(['es', 'en'])('offers "add my API key" → Settings → Integrations and the upgrade (%s)', async (lang) => {
    mockLang.current = lang;
    mockDb.profile = profile;
    await mount();
    const pu = translations[lang].plan_usage;
    const blocked = byTestId('credits-blocked');
    expect(blocked.textContent).toContain(pu[messageKey]);
    expect(blocked.textContent).toMatch(/OpenAI/);
    const addKey = byTestId('credits-add-key-btn');
    expect(addKey.textContent).toBe(pu.add_own_api_key);
    expect(byTestId('credits-upgrade-btn')).not.toBeNull();
    await click(addKey);
    await flush();
    expect(nav.location.pathname).toBe('/settings/integrations');
  });
});
