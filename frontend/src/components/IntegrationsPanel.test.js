// Settings → Integrations must not offer the "own OpenAI key" card while the
// backend can't use a saved key (ai_billing.get_user_api_key is a stub).
jest.mock('../lib/supabaseClient', () => ({ supabase: {} }));
jest.mock('../lib/authFetch', () => ({ authFetch: jest.fn() }));
jest.mock('sonner', () => ({ toast: { success: jest.fn(), warning: jest.fn(), error: jest.fn() } }));
const mockLang = { current: 'es' };
jest.mock('../context/LanguageContext', () => {
  // eslint-disable-next-line global-require
  const { translations } = require('../i18n/translations');
  const resolve = (tree, key) => key.split('.').reduce((node, part) => (node == null ? node : node[part]), tree);
  const t = (k) => {
    const v = resolve(translations[mockLang.current], k);
    return typeof v === 'string' ? v : k;
  };
  return { useLanguage: () => ({ lang: mockLang.current, t }) };
});

/* eslint-disable import/first */
import React from 'react';
import IntegrationsPanel, { VISIBLE_INTEGRATIONS } from './IntegrationsPanel';
import { OWN_OPENAI_KEY_ENABLED } from '../lib/billing';
import { authFetch } from '../lib/authFetch';
import { render, flush, byTestId } from '../test/render';
/* eslint-enable import/first */

const jsonResponse = (body) => ({ ok: true, status: 200, json: async () => body });

let view;

beforeEach(() => {
  jest.clearAllMocks();
  authFetch.mockImplementation(async (url) => {
    if (String(url).endsWith('/api/integrations')) {
      // Even a workspace that saved a key before launch gets no card.
      return jsonResponse([{ provider: 'openai', status: 'connected', config: { model: 'gpt-4o' } }]);
    }
    return jsonResponse({ status: 'healthy', checks: [] });
  });
});

afterEach(async () => {
  await view?.unmount();
  view = null;
});

it('keeps the own-OpenAI-key feature flag off for launch', () => {
  expect(OWN_OPENAI_KEY_ENABLED).toBe(false);
  expect(VISIBLE_INTEGRATIONS.map((m) => m.id)).toEqual(['crm', 'webhook']);
});

describe.each(['es', 'en'])('IntegrationsPanel (%s)', (lang) => {
  beforeEach(() => {
    mockLang.current = lang;
  });

  it('renders CRM and webhooks but no OpenAI card, AI group or Emergent copy', async () => {
    view = await render(<IntegrationsPanel />);
    await flush();

    expect(byTestId('integrations-loading')).toBeNull();
    expect(byTestId('crm-integration-card')).not.toBeNull();
    expect(byTestId('webhook-integration-card')).not.toBeNull();

    expect(byTestId('openai-integration-card')).toBeNull();
    expect(byTestId('openai-api_key-input')).toBeNull();
    expect(byTestId('connect-openai-button')).toBeNull();
    expect(byTestId('integration-group-ai')).toBeNull();

    const text = byTestId('integrations-panel').textContent;
    expect(text).not.toMatch(/emergent/i);
    expect(text).not.toMatch(/openai/i);
  });
});
