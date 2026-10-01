// Settings → Integrations: the OpenAI card is the workspace's OWN OpenAI key
// ("conectar su propia API"). Once saved, the workspace's AI runs on it and
// OpenAI bills the customer; no Quantro credits are consumed. Leader+ only.
jest.mock('../lib/supabaseClient', () => ({ supabase: {} }));
jest.mock('../lib/authFetch', () => ({ authFetch: jest.fn() }));
jest.mock('sonner', () => ({ toast: { success: jest.fn(), warning: jest.fn(), error: jest.fn() } }));
const mockAuth = { workspaces: [], currentWorkspaceId: 'ws_a' };
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
  const lang = { t };
  return { useLanguage: () => ({ ...lang, lang: mockLang.current }) };
});

/* eslint-disable import/first */
import React, { act } from 'react';
import { toast } from 'sonner';
import IntegrationsPanel from './IntegrationsPanel';
import { authFetch } from '../lib/authFetch';
import { OPENAI_DEFAULT_MODEL, OPENAI_MODEL_OPTIONS } from '../lib/billing';
import { translations } from '../i18n/translations';
import { render, flush, click, byTestId } from '../test/render';
/* eslint-enable import/first */

const jsonResponse = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });

const OPENAI_DISCONNECTED = { provider: 'openai', status: 'disconnected', config: {} };
const OPENAI_CONNECTED = {
  provider: 'openai',
  status: 'connected',
  config: { has_api_key: true, model: 'gpt-4o' },
  last_test_at: '2026-09-30T12:00:00+00:00',
  last_test_ok: true,
  last_test_reason: null,
};

let rows;
let testResponse;
let putResponse;
let view;

const asRole = (role) => {
  mockAuth.workspaces = [{ workspace_id: 'ws_a', name: 'A', role, is_current: true }];
};

const callsTo = (suffix, method) => authFetch.mock.calls.filter(
  ([url, opts]) => String(url).endsWith(suffix) && (opts?.method || 'GET') === method,
);

// React-controlled input: use the native setter so onChange fires.
async function typeInto(input, value) {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  await act(async () => {
    setter.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

async function mount() {
  view = await render(<IntegrationsPanel />);
  await flush();
}

beforeEach(() => {
  jest.clearAllMocks();
  mockLang.current = 'es';
  asRole('owner');
  rows = [OPENAI_DISCONNECTED];
  testResponse = { success: true, status: 'ok', reason: null, model: 'gpt-4o', message: 'Conexión con OpenAI verificada.' };
  putResponse = null;
  authFetch.mockImplementation(async (url, opts = {}) => {
    const u = String(url);
    if (u.endsWith('/api/integrations') && !opts.method) return jsonResponse(rows);
    if (u.endsWith('/api/integrations/openai/test')) return jsonResponse(testResponse);
    if (u.endsWith('/api/integrations/openai') && opts.method === 'PUT') {
      return putResponse || jsonResponse({ ...OPENAI_CONNECTED, last_test_at: null });
    }
    return jsonResponse({ status: 'healthy', checks: [] });
  });
});

afterEach(async () => {
  await view?.unmount();
  view = null;
});

describe.each(['es', 'en'])('OpenAI own-key card copy (%s)', (lang) => {
  beforeEach(() => {
    mockLang.current = lang;
  });

  it('explains that the workspace AI runs on the customer key and never mentions Emergent', async () => {
    await mount();
    const card = byTestId('openai-integration-card');
    expect(card).not.toBeNull();
    expect(byTestId('openai-helper').textContent).toBe(translations[lang].integrations.openai.helper);
    expect(card.textContent).not.toMatch(/emergent/i);
    expect(byTestId('integrations-panel').textContent).not.toMatch(/emergent/i);
  });
});

it('uses the exact ES copy requested by the owner', () => {
  expect(translations.es.integrations.openai.helper).toMatch(
    /^Usa tu propia clave de OpenAI: las funciones de IA de este espacio de trabajo usarán tu clave y OpenAI te cobrará directamente; no se consumen créditos de Quantro\./,
  );
  expect(translations.en.integrations.openai.helper).toMatch(/OpenAI will bill you directly; no Quantro credits are used/);
  // Google Limited Use: Gmail/Calendar data reaches OpenAI on the customer's key, so saving it commits to data sharing off.
  expect(translations.es.integrations.openai.helper).toMatch(/mantener desactivado el uso compartido de datos con OpenAI/);
  expect(translations.en.integrations.openai.helper).toMatch(/keep data sharing with OpenAI turned off/);
});

it('offers exactly the backend model allowlist, gpt-4o-mini by default', () => {
  expect(OPENAI_MODEL_OPTIONS.map((o) => o.value)).toEqual(['gpt-4o-mini', 'gpt-4o', 'gpt-4.1-mini']);
  expect(OPENAI_DEFAULT_MODEL).toBe('gpt-4o-mini');
  ['es', 'en'].forEach((lang) => {
    OPENAI_MODEL_OPTIONS.forEach((o) => {
      const key = o.labelKey.split('.').pop();
      expect(typeof translations[lang].integrations.openai[key]).toBe('string');
    });
  });
});

describe('roles', () => {
  it.each(['leader', 'owner'])('%s gets the key form and the connect button', async (role) => {
    asRole(role);
    await mount();
    expect(byTestId('openai-api_key-input')).not.toBeNull();
    expect(byTestId('connect-openai-button')).not.toBeNull();
    expect(byTestId('openai-leader-only')).toBeNull();
  });

  it.each(['viewer', 'member', 'accountant'])('%s sees the status but no key controls', async (role) => {
    asRole(role);
    rows = [OPENAI_CONNECTED];
    await mount();
    expect(byTestId('openai-integration-card')).not.toBeNull();
    expect(byTestId('status-badge-connected')).not.toBeNull();
    expect(byTestId('openai-api_key-input')).toBeNull();
    expect(byTestId('connect-openai-button')).toBeNull();
    expect(byTestId('test-openai-button')).toBeNull();
    expect(byTestId('update-openai-button')).toBeNull();
    expect(byTestId('disconnect-openai-button')).toBeNull();
    expect(byTestId('openai-leader-only').textContent).toContain(translations.es.integrations.leader_only);
  });
});

describe('status', () => {
  it('shows key saved, the model the workspace AI uses and the last passing test', async () => {
    rows = [OPENAI_CONNECTED];
    await mount();
    expect(byTestId('status-badge-connected')).not.toBeNull();
    expect(byTestId('openai-key-saved').textContent).toContain('Clave guardada');
    expect(byTestId('openai-active').textContent).toContain('usa esta clave (modelo gpt-4o)');
    expect(byTestId('openai-last-test').dataset.state).toBe('ok');
    expect(byTestId('openai-last-test').textContent).toContain('Última prueba correcta');
    // The secret input never shows the key; it says one is saved.
    expect(byTestId('openai-api_key-input').value).toBe('');
    expect(byTestId('openai-api_key-input').getAttribute('placeholder')).toBe(
      translations.es.integrations.openai.api_key_saved_placeholder,
    );
  });

  it('shows why the last test failed', async () => {
    rows = [{ ...OPENAI_CONNECTED, last_test_ok: false, last_test_reason: 'own_key_quota_exhausted' }];
    mockLang.current = 'en';
    await mount();
    const line = byTestId('openai-last-test');
    expect(line.dataset.state).toBe('failed');
    expect(line.textContent).toContain('Last test failed');
    expect(line.textContent).toContain('The OpenAI account is out of credit or quota.');
  });

  it('says a connected key was never tested', async () => {
    rows = [{ ...OPENAI_CONNECTED, last_test_at: null, last_test_ok: null }];
    await mount();
    expect(byTestId('openai-last-test').dataset.state).toBe('never');
  });

  it('does not call a row "connected" when no key is stored', async () => {
    rows = [{ provider: 'openai', status: 'connected', config: { model: 'gpt-4o' } }];
    await mount();
    expect(byTestId('status-badge-disconnected')).not.toBeNull();
    expect(byTestId('connect-openai-button')).not.toBeNull();
    expect(byTestId('openai-active')).toBeNull();
  });
});

describe('actions', () => {
  it('saves the key and immediately runs the real connection test', async () => {
    await mount();
    await typeInto(byTestId('openai-api_key-input'), 'sk-proj-test-key-1234567890');
    await click(byTestId('connect-openai-button'));
    await flush(6);

    const [put] = callsTo('/api/integrations/openai', 'PUT');
    expect(JSON.parse(put[1].body)).toEqual({
      status: 'connected',
      config: { api_key: 'sk-proj-test-key-1234567890', model: OPENAI_DEFAULT_MODEL },
    });
    expect(callsTo('/api/integrations/openai/test', 'POST')).toHaveLength(1);
    expect(toast.success).toHaveBeenCalledWith(expect.any(String), { description: 'Conexión con OpenAI verificada.' });
  });

  it('sends the model the backend uses when a legacy model is saved (e.g. gpt-4-turbo)', async () => {
    // A legacy row from the old card: status connected but no key stored.
    rows = [{ provider: 'openai', status: 'connected', config: { model: 'gpt-4-turbo' } }];
    await mount();
    await typeInto(byTestId('openai-api_key-input'), 'sk-proj-test-key-1234567890');
    await click(byTestId('connect-openai-button'));
    await flush(6);

    const [put] = callsTo('/api/integrations/openai', 'PUT');
    expect(JSON.parse(put[1].body).config.model).toBe(OPENAI_DEFAULT_MODEL);
  });

  it('shows the backend validation message when the key is rejected on save', async () => {
    putResponse = jsonResponse({ detail: { error: 'invalid_openai_key_format', message: 'Eso no parece una clave.' } }, 400);
    await mount();
    await typeInto(byTestId('openai-api_key-input'), 'not-a-key');
    await click(byTestId('connect-openai-button'));
    await flush(6);
    expect(toast.error).toHaveBeenCalledWith(expect.any(String), { description: 'Eso no parece una clave.' });
    expect(callsTo('/api/integrations/openai/test', 'POST')).toHaveLength(0);
  });

  it('reports a failed real test with the backend reason and refreshes the status', async () => {
    rows = [OPENAI_CONNECTED];
    testResponse = { success: false, status: 'failed', reason: 'own_key_invalid', message: 'OpenAI rechazó la clave.' };
    await mount();
    const listCallsBefore = callsTo('/api/integrations', 'GET').length;
    await click(byTestId('test-openai-button'));
    await flush(6);
    expect(toast.error).toHaveBeenCalledWith(
      translations.es.integrations.toasts.test_fail_real.replace('{{provider}}', 'openai'),
      { description: 'OpenAI rechazó la clave.' },
    );
    expect(callsTo('/api/integrations', 'GET').length).toBe(listCallsBefore + 1);
  });

  it('disconnect asks the backend to forget the key', async () => {
    rows = [OPENAI_CONNECTED];
    await mount();
    await click(byTestId('disconnect-openai-button'));
    await flush();
    const [put] = callsTo('/api/integrations/openai', 'PUT');
    expect(JSON.parse(put[1].body)).toEqual({ status: 'disconnected', config: {} });
  });
});
