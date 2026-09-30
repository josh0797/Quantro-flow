// Plan & usage: with the own-OpenAI-key option hidden, an out-of-credits
// user is told to upgrade or wait for the next monthly cycle, and the only
// action offered is the existing upgrade flow (PlanSelectorDialog).
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
jest.mock('sonner', () => ({ toast: { success: jest.fn(), info: jest.fn(), error: jest.fn() } }));
const mockAuth = {
  user: { user_id: 'user-1', email: 'owner@example.com', name: 'Owner' },
  workspaces: [],
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
import { translations } from '../i18n/translations';
import { render, flush, click, byTestId } from '../test/render';
/* eslint-enable import/first */

const USED_UP_PRO = {
  id: 'user-1',
  plan: 'pro',
  subscription_status: 'active',
  ai_credits_total: 10,
  ai_credits_used: 10,
  ai_credits_remaining: 0,
};

let view;

async function mount() {
  view = await render(
    <MemoryRouter initialEntries={['/plan']}>
      <PlanAndUsage />
    </MemoryRouter>,
  );
  await flush();
}

afterEach(async () => {
  await view?.unmount();
  view = null;
});

describe.each([
  ['es', 'Actualiza tu plan o espera al siguiente ciclo mensual'],
  ['en', 'Upgrade your plan or wait for the next monthly cycle'],
])('PlanAndUsage out of credits (%s)', (lang, expected) => {
  beforeEach(() => {
    mockLang.current = lang;
    mockDb.profile = USED_UP_PRO;
  });

  it('offers upgrade / next monthly cycle and no "add my API key" CTA', async () => {
    await mount();

    const blocked = byTestId('credits-blocked');
    expect(blocked).not.toBeNull();
    expect(blocked.textContent).toContain(expected);
    expect(blocked.textContent).not.toMatch(/api key/i);

    expect(byTestId('credits-add-key-btn')).toBeNull();
    expect(byTestId('plan-usage-page').textContent).not.toContain(
      translations[lang].plan_usage.add_own_api_key,
    );

    const upgrade = byTestId('credits-upgrade-btn');
    expect(upgrade).not.toBeNull();
    expect(upgrade.textContent).toBe(translations[lang].billing.upgrade_plan);
    expect(byTestId('plan-selector-dialog')).toBeNull();
    await click(upgrade);
    await flush();
    expect(byTestId('plan-selector-dialog')).not.toBeNull();
  });
});

it('shows only the upgrade path on a plan without included credits (Essential)', async () => {
  mockLang.current = 'es';
  mockDb.profile = { id: 'user-1', plan: 'essential', ai_credits_total: 0, ai_credits_used: 0, ai_credits_remaining: 0 };
  await mount();

  const blocked = byTestId('credits-blocked');
  expect(blocked.textContent).toContain(translations.es.plan_usage.credits_plan_not_included);
  expect(blocked.textContent).not.toContain('ciclo mensual');
  expect(byTestId('credits-add-key-btn')).toBeNull();
  expect(byTestId('credits-upgrade-btn')).not.toBeNull();
});

it.each(['es', 'en'])('keeps the low-credits warning free of own-key advice (%s)', (lang) => {
  const warning = translations[lang].plan_usage.credits_low_warning.toLowerCase();
  expect(warning).not.toContain('api key');
  expect(warning).toContain(lang === 'es' ? 'actualizar tu plan' : 'upgrading your plan');
});
