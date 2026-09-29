// src/lib/productHub.js
// Quantro Product Hub links for Quantro Flow. The hub (quantroos.com) and the
// Product Capability Registry live in the Quantro OS repo (konta/src/product);
// this module mirrors its URL conventions so no page hardcodes a hub URL, and
// reads the published registry for the Help & Learning entries so the copy
// stays the single source of truth.
//
//   Learn page   → https://quantroos.com/learn/flow/<capability>   (capability = registry id without "flow-")
//   Workflow     → https://quantroos.com/learn/workflows/<id>
//   Live Demo    → https://quantro.technology/demo(?capability=<id>)   (the Atlas demo runs in Quantro OS)

import { useEffect, useState } from 'react';

export const PRODUCT_HUB_BASE_URL = 'https://quantroos.com';
export const QUANTRO_OS_URL = 'https://quantro.technology';
export const PRODUCT_REGISTRY_URL = `${QUANTRO_OS_URL}/product-registry.json`;

export const HUB_ROUTES = {
  overview: '/overview',
  flow: '/learn/flow',
  tutorials: '/learn/tutorials',
  workflows: '/learn/workflows',
};

/** Flow capability ids are "flow-<route>" in the registry; hub paths drop the prefix. */
const stripFlowPrefix = (id) => (id.startsWith('flow-') ? id.slice(5) : id);

export const buildHubUrl = (path) => `${PRODUCT_HUB_BASE_URL}${path}`;
export const buildLearnUrl = (capabilityId, product = 'quantro-flow') =>
  product === 'quantro-flow'
    ? `${PRODUCT_HUB_BASE_URL}/learn/flow/${stripFlowPrefix(capabilityId)}`
    : `${PRODUCT_HUB_BASE_URL}/learn/${capabilityId}`;
export const buildWorkflowUrl = (workflowId) => `${PRODUCT_HUB_BASE_URL}/learn/workflows/${workflowId}`;
export const buildDemoUrl = (capabilityId) =>
  `${QUANTRO_OS_URL}${capabilityId ? `/demo?capability=${encodeURIComponent(capabilityId)}` : '/demo'}`;

/** Flow route → registry capability id (used by the contextual "Learn" links). */
export const FLOW_ROUTE_CAPABILITY = {
  inbox: 'flow-inbox',
  schedule: 'flow-calendar',
  crm: 'flow-crm',
  content: 'flow-content',
  automation: 'flow-automation',
  connect: 'flow-connectors',
};

/**
 * Fallback Help & Learning entries (same ids/labels as the registry) so the
 * section renders even if the registry cannot be fetched. Labels are
 * overwritten by the registry titles when it loads.
 */
export const FLOW_HELP_FALLBACK = [
  { id: 'flow-inbox',      label: { en: 'Smart Inbox',    es: 'Smart Inbox' } },
  { id: 'flow-calendar',   label: { en: 'Calendar',       es: 'Calendario' } },
  { id: 'flow-crm',        label: { en: 'CRM',            es: 'CRM' } },
  { id: 'flow-content',    label: { en: 'Content Engine', es: 'Content Engine' } },
  { id: 'flow-automation', label: { en: 'Automation',     es: 'Automatización' } },
  { id: 'flow-connectors', label: { en: 'Connectors',     es: 'Conectores' } },
];

let registryPromise = null;

/** Fetch the published registry once per session (cached in memory). */
export function loadProductRegistry() {
  if (!registryPromise) {
    registryPromise = fetch(PRODUCT_REGISTRY_URL, { headers: { Accept: 'application/json' } })
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`registry ${res.status}`))))
      .catch((err) => { registryPromise = null; throw err; });
  }
  return registryPromise;
}

/**
 * Help & Learning entries for Flow: [{ id, title: {en,es}, description: {en,es}, learnUrl, duration }].
 * Registry-first, static fallback while loading / offline.
 */
export function useFlowHelpEntries() {
  const [entries, setEntries] = useState(() =>
    FLOW_HELP_FALLBACK.map((e) => ({ id: e.id, title: e.label, description: null, learnUrl: buildLearnUrl(e.id), duration: null })),
  );
  useEffect(() => {
    let alive = true;
    loadProductRegistry()
      .then((doc) => {
        if (!alive) return;
        const flow = (doc.capabilities || []).filter((c) => c.product === 'quantro-flow');
        if (flow.length === 0) return;
        setEntries(flow.map((c) => ({
          id: c.id,
          title: c.title,
          description: c.shortDescription,
          learnUrl: buildHubUrl(c.learnRoute),
          duration: c.tutorial?.duration || null,
        })));
      })
      .catch(() => { /* keep the fallback */ });
    return () => { alive = false; };
  }, []);
  return entries;
}

/** GA4 / dataLayer event, no-op when neither exists. Names match the Product Hub and Quantro OS. */
export function trackHelp(event, params = {}) {
  try {
    if (typeof window === 'undefined') return;
    const payload = { event_category: 'product_education', product: 'quantro-flow', ...params };
    if (typeof window.gtag === 'function') { window.gtag('event', event, payload); return; }
    if (Array.isArray(window.dataLayer)) window.dataLayer.push({ event, ...payload });
  } catch { /* never break the app for analytics */ }
}
