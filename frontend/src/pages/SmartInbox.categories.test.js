// date-fns v3+ ships ESM that Jest 27 can't transform — stub what the page imports.
jest.mock('date-fns', () => ({ format: () => 'Sep 30 10:00', parseISO: (s) => new Date(s) }));
jest.mock('framer-motion', () => {
  const React = require('react');
  const strip = ({ initial, animate, exit, transition, layout, ...rest }) => rest;
  const cache = {};
  return {
    motion: new Proxy({}, {
      get: (_, tag) => {
        cache[tag] = cache[tag] || React.forwardRef((props, ref) => React.createElement(tag, { ...strip(props), ref }));
        return cache[tag];
      },
    }),
    AnimatePresence: ({ children }) => React.createElement(React.Fragment, null, children),
  };
});
jest.mock('../lib/api', () => ({
  getInbox: jest.fn(),
  getInboxCategories: jest.fn(),
  reclassifyInbox: jest.fn(),
  analyzeInboxItem: jest.fn(),
  approveInboxAction: jest.fn(),
  declineInboxAction: jest.fn(),
  batchAnalyzeInbox: jest.fn(),
  batchApproveInbox: jest.fn(),
  updateInboxDetails: jest.fn(),
  approveWithOverrides: jest.fn(),
}));
jest.mock('sonner', () => ({
  toast: { success: jest.fn(), warning: jest.fn(), error: jest.fn(), info: jest.fn() },
}));
jest.mock('../components/DataModeBanner', () => () => null);
jest.mock('../components/LiveEmptyState', () => () => require('react').createElement('div', { 'data-testid': 'live-empty-state' }));
// Stable `t` / profile, like the real memoized ones; tests flip them.
const mockLang = { t: (k, vars) => (vars && vars.count !== undefined ? `${k}:${vars.count}` : k), lang: 'es' };
jest.mock('../context/LanguageContext', () => ({ useLanguage: () => mockLang }));
const mockProfile = { profile: { industry: 'real_estate', simulation_mode: false, entity_labels: {} } };
jest.mock('../contexts/BusinessProfileContext', () => ({ useBusinessProfile: () => mockProfile }));

/* eslint-disable import/first */
import React, { act } from 'react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { toast } from 'sonner';
import SmartInbox from './SmartInbox';
import { getInbox, getInboxCategories, reclassifyInbox } from '../lib/api';
import { render, flush, click, byTestId, createNavSpy } from '../test/render';
/* eslint-enable import/first */

// Radix Checkbox measures itself; jsdom 16 has no ResizeObserver.
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

// What GET /api/inbox/categories serves (backend/inbox_categories.py).
const cat = (key, label_es, label_en, suggested_action = null) => ({ key, label_es, label_en, suggested_action });
const TAIL = [cat('spam_promocion', 'Spam / promoción', 'Spam / promotion', 'ignore'), cat('otro', 'Otro', 'Other')];
const REAL_ESTATE = {
  industry: 'real_estate', has_industry: true, category_set: 'real_estate',
  label_es: 'Bienes raíces', label_en: 'Real estate',
  categories: [
    cat('agendar_visita', 'Agendar visita', 'Schedule a viewing', 'schedule_meeting'),
    cat('info_propiedad', 'Información de propiedad', 'Property inquiry', 'create_contact'),
    cat('captar_propiedad', 'Vender o rentar su propiedad', 'List a property', 'schedule_meeting'),
    cat('oferta_negociacion', 'Oferta o negociación', 'Offer / negotiation', 'send_follow_up'),
    cat('credito_documentacion', 'Crédito hipotecario / documentación', 'Mortgage / paperwork', 'send_follow_up'),
    cat('renta_mantenimiento', 'Renta y mantenimiento', 'Rental & maintenance', 'flag_review'),
    cat('postventa', 'Seguimiento postventa', 'After-sale follow-up', 'send_follow_up'),
    ...TAIL,
  ],
};
const RETAIL = {
  industry: 'ecommerce', has_industry: true, category_set: 'retail',
  label_es: 'Comercio / e-commerce', label_en: 'Retail / e-commerce',
  categories: [
    cat('estado_pedido', 'Estado de pedido', 'Order status', 'send_follow_up'),
    cat('pedido_entregado', 'Pedido entregado / confirmación', 'Order delivered / confirmation'),
    cat('devolucion_reembolso', 'Devolución o reembolso', 'Return or refund', 'flag_review'),
    cat('cambio_producto', 'Cambio de producto', 'Exchange', 'flag_review'),
    cat('reclamo_garantia', 'Reclamo o garantía', 'Complaint / warranty', 'flag_review'),
    cat('pago_factura', 'Pago o factura', 'Payment / invoice', 'send_follow_up'),
    cat('disponibilidad_producto', 'Disponibilidad de producto', 'Product availability', 'create_contact'),
    ...TAIL,
  ],
};
const GENERIC_UNSET = {
  industry: 'other', has_industry: false, category_set: 'generic', label_es: 'General', label_en: 'General',
  categories: [cat('nuevo_cliente', 'Nuevo cliente / venta', 'New customer / sale', 'create_contact'), ...TAIL],
};
const REAL_ESTATE_KEYS = ['agendar_visita', 'info_propiedad', 'oferta_negociacion', 'renta_mantenimiento', 'postventa'];
const RETAIL_KEYS = ['estado_pedido', 'pedido_entregado', 'devolucion_reembolso', 'cambio_producto', 'pago_factura'];

const item = (inbox_id, subject, ai_category, extra = {}) => ({
  inbox_id, subject, ai_category, from_name: 'Cliente', from_email: 'c@example.com', body: '…',
  received_at: '2026-09-30T10:00:00Z', read: true, status: 'processed',
  ai_intent: { intent: 'inquiry', confidence: 0.9, summary: 's', entities: {} },
  ai_suggested_action: { type: 'flag_review', description: 'd' },
  ...extra,
});

let view;
let nav;

async function mount() {
  nav = createNavSpy();
  view = await render(
    <MemoryRouter initialEntries={['/inbox']}>
      <nav.Probe />
      <Routes>
        <Route path="/inbox" element={<SmartInbox />} />
        <Route path="/settings/:tab?" element={<div data-testid="settings-screen" />} />
      </Routes>
    </MemoryRouter>,
  );
  await flush(5);
}

const chips = () => [...document.querySelectorAll('[data-testid="inbox-category-chip"]')];
const listItems = () => [...document.querySelectorAll('[data-testid="smart-inbox-item"]')];

beforeEach(() => {
  jest.clearAllMocks();
  mockLang.lang = 'es';
  mockProfile.profile = { industry: 'real_estate', simulation_mode: false, entity_labels: {} };
});

afterEach(async () => {
  await view?.unmount();
  view = null;
});

describe('SmartInbox industry categories', () => {
  it('real-estate workspace: real-estate chips and filter only, filter narrows the list', async () => {
    getInboxCategories.mockResolvedValue(REAL_ESTATE);
    getInbox.mockResolvedValue([
      item('i-1', 'Quiero ver la casa', 'agendar_visita'),
      item('i-2', 'Ofrezco 2.1 millones', 'oferta_negociacion'),
      item('i-3', 'Nuevo correo', undefined, { status: 'new', ai_intent: null, ai_suggested_action: null }),
    ]);
    await mount();

    expect(chips().map((c) => [c.dataset.category, c.textContent])).toEqual([
      ['agendar_visita', 'Agendar visita'],
      ['oferta_negociacion', 'Oferta o negociación'],
    ]);
    for (const key of REAL_ESTATE_KEYS) expect(byTestId(`inbox-category-filter-${key}`)).not.toBeNull();
    for (const key of RETAIL_KEYS) expect(byTestId(`inbox-category-filter-${key}`)).toBeNull();
    expect(byTestId('inbox-industry-hint')).toBeNull();

    await click(byTestId('inbox-category-filter-agendar_visita'));
    expect(listItems()).toHaveLength(1);
    expect(listItems()[0].textContent).toContain('Quiero ver la casa');
    expect(byTestId('inbox-category-filter-agendar_visita').getAttribute('aria-pressed')).toBe('true');

    await click(byTestId('inbox-category-filter-all'));
    expect(listItems()).toHaveLength(3);
  });

  it('retail workspace: retail chips and filter only (EN labels), never real-estate ones', async () => {
    mockLang.lang = 'en';
    mockProfile.profile = { industry: 'ecommerce', simulation_mode: false, entity_labels: {} };
    getInboxCategories.mockResolvedValue(RETAIL);
    getInbox.mockResolvedValue([
      item('i-1', 'I want to return my order', 'devolucion_reembolso'),
      item('i-2', 'Delivered!', 'pedido_entregado'),
      // Categorized before the industry changed: not in this workspace's list → no chip.
      item('i-3', 'Old viewing request', 'agendar_visita'),
    ]);
    await mount();

    expect(chips().map((c) => [c.dataset.category, c.textContent])).toEqual([
      ['devolucion_reembolso', 'Return or refund'],
      ['pedido_entregado', 'Order delivered / confirmation'],
    ]);
    for (const key of RETAIL_KEYS) expect(byTestId(`inbox-category-filter-${key}`)).not.toBeNull();
    for (const key of REAL_ESTATE_KEYS) expect(byTestId(`inbox-category-filter-${key}`)).toBeNull();
    expect(byTestId('inbox-category-filter').textContent).toContain('Return or refund');
    expect(byTestId('inbox-category-filter').textContent).not.toContain('Schedule a viewing');

    await click(byTestId('inbox-category-filter-devolucion_reembolso'));
    expect(listItems()).toHaveLength(1);
    expect(listItems()[0].textContent).toContain('I want to return my order');
  });

  it('shows the category in the Review list and detail panel', async () => {
    getInboxCategories.mockResolvedValue(REAL_ESTATE);
    getInbox.mockResolvedValue([item('i-1', 'Quiero ver la casa', 'agendar_visita')]);
    await mount();

    const reviewTab = [...document.querySelectorAll('[role="tab"]')].find((el) => el.textContent.includes('Review'));
    await act(async () => {
      reviewTab.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, button: 0 }));
    });
    await flush();
    const row = [...document.querySelectorAll('.cursor-pointer')].find((el) => el.textContent.includes('Quiero ver la casa'));
    await click(row);
    await flush();

    const detail = byTestId('smart-inbox-detail');
    expect(detail).not.toBeNull();
    const detailChip = detail.querySelector('[data-testid="inbox-category-chip"]');
    expect(detailChip.dataset.category).toBe('agendar_visita');
    expect(detailChip.textContent).toBe('Agendar visita');
  });

  it('a category with no mail shows a filtered-empty card, not the connect-your-inbox state', async () => {
    getInboxCategories.mockResolvedValue(REAL_ESTATE);
    getInbox.mockResolvedValue([item('i-1', 'Quiero ver la casa', 'agendar_visita')]);
    await mount();

    await click(byTestId('inbox-category-filter-postventa'));
    expect(listItems()).toHaveLength(0);
    expect(byTestId('inbox-category-empty')).not.toBeNull();
    expect(byTestId('live-empty-state')).toBeNull();
  });

  it('no industry yet: gentle hint linking to Settings → Business Profile', async () => {
    mockProfile.profile = { industry: 'other', simulation_mode: false, entity_labels: {} };
    getInboxCategories.mockResolvedValue(GENERIC_UNSET);
    getInbox.mockResolvedValue([item('i-1', 'Hola', 'nuevo_cliente')]);
    await mount();

    expect(byTestId('inbox-industry-hint')).not.toBeNull();
    // Cancelable, like a real click: the router handles it (jsdom can't navigate).
    await act(async () => {
      byTestId('inbox-industry-hint-link').dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 }));
    });
    await flush();
    expect(nav.location.pathname).toBe('/settings/profile');
    expect(byTestId('settings-screen')).not.toBeNull();
  });

  it('"Reclasificar" re-categorizes and refreshes the inbox', async () => {
    getInboxCategories.mockResolvedValue(REAL_ESTATE);
    getInbox.mockResolvedValue([item('i-1', 'Quiero ver la casa', 'agendar_visita')]);
    reclassifyInbox.mockResolvedValue({ success: true, reclassified: 3, considered: 4, skipped_up_to_date: 1, failed: 0 });
    await mount();
    const fetchesBefore = getInbox.mock.calls.length;

    await click(byTestId('inbox-reclassify-button'));
    await flush();

    expect(reclassifyInbox).toHaveBeenCalledTimes(1);
    expect(toast.success).toHaveBeenCalledWith('inbox_categories.toast_done:3');
    expect(getInbox.mock.calls.length).toBeGreaterThan(fetchesBefore);
  });

  it('keeps working (no chips, no filter) when categories cannot be loaded', async () => {
    getInboxCategories.mockRejectedValue(new Error('offline'));
    getInbox.mockResolvedValue([item('i-1', 'Quiero ver la casa', 'agendar_visita')]);
    const warn = jest.spyOn(console, 'warn').mockImplementation(() => {});
    await mount();
    warn.mockRestore();

    expect(listItems()).toHaveLength(1);
    expect(chips()).toHaveLength(0);
    expect(byTestId('inbox-category-filter')).toBeNull();
  });
});
