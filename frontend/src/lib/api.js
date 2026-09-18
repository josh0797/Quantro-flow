import axios from 'axios';
import { supabase } from './supabaseClient';

const API_BASE = process.env.REACT_APP_BACKEND_URL || '';

/**
 * Legacy helpers kept around so older imports keep compiling. They now
 * read/write the Supabase session indirectly. Prefer using the Supabase
 * client directly (or useAuth()) in new code.
 */
export const getStoredToken = () => {
  // Read the token synchronously from the cache that @supabase/supabase-js
  // maintains in localStorage. We parse it best-effort — if the structure
  // changes we fall back to null.
  try {
    const raw = localStorage.getItem('quantro-flow-auth');
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed?.access_token || parsed?.currentSession?.access_token || null;
  } catch (_) {
    return null;
  }
};

// Historic setter — noop now (Supabase owns the session).
export const setStoredToken = (_token) => {};

const api = axios.create({
  baseURL: `${API_BASE}/api`,
  headers: { 'Content-Type': 'application/json' },
});

// Attach the current Supabase access token on every request. We call
// supabase.auth.getSession() so we always pick up the freshest token
// (the SDK auto-refreshes in the background).
api.interceptors.request.use(async (config) => {
  try {
    const { data } = await supabase.auth.getSession();
    const token = data?.session?.access_token;
    if (token) {
      config.headers = config.headers || {};
      config.headers.Authorization = `Bearer ${token}`;
    }
  } catch (e) {
    // If we cannot fetch the Supabase session (network blip, SDK crash)
    // we still want the request to go through unauthenticated so the
    // server can return a clean 401, rather than throwing client-side.
    // Surface the cause in dev tools for visibility.
    // eslint-disable-next-line no-console
    console.warn('[api] could not attach Supabase Bearer token:', e?.message || e);
  }
  return config;
});

// Global 401 handler — let the UI redirect to /login.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      window.dispatchEvent(new CustomEvent('auth:unauthorized'));
    }
    return Promise.reject(error);
  },
);

// Auth (Supabase-backed server helpers)
export const authMe = () => api.get('/auth/me').then(r => r.data);
export const authSwitchWorkspace = (workspace_id) => api.post('/auth/workspaces/switch', { workspace_id }).then(r => r.data);
export const authCreateWorkspace = (name) => api.post('/auth/workspaces', { name }).then(r => r.data);

// Members & RBAC (Phase 7b)
export const listMembers = (workspace_id) =>
  api.get(`/workspaces/${workspace_id}/members`).then(r => r.data);
export const updateMemberRole = (workspace_id, user_id, role) =>
  api.patch(`/workspaces/${workspace_id}/members/${user_id}`, { role }).then(r => r.data);
export const removeMember = (workspace_id, user_id) =>
  api.delete(`/workspaces/${workspace_id}/members/${user_id}`).then(r => r.data);

// Workspace invites
export const listInvites = (workspace_id) =>
  api.get(`/workspaces/${workspace_id}/invites`).then(r => r.data);
export const createInvite = (workspace_id, payload) =>
  api.post(`/workspaces/${workspace_id}/invites`, payload).then(r => r.data);
export const revokeInvite = (workspace_id, invite_id) =>
  api.delete(`/workspaces/${workspace_id}/invites/${invite_id}`).then(r => r.data);
export const peekInvite = (token) => api.get(`/invites/${token}`).then(r => r.data);
export const acceptInvite = (token) => api.post(`/invites/${token}/accept`).then(r => r.data);

// Onboarding
export const getOnboarding = (workspace_id) =>
  api.get(`/workspaces/${workspace_id}/onboarding`).then(r => r.data);
export const upsertOnboardingStep = (workspace_id, member_user_id, step_key, payload) =>
  api.post(`/workspaces/${workspace_id}/onboarding/${member_user_id}/steps/${step_key}`, payload).then(r => r.data);
export const markOnboardingComplete = (workspace_id, member_user_id) =>
  api.post(`/workspaces/${workspace_id}/onboarding/${member_user_id}/complete`).then(r => r.data);

// Audit timeline
export const getAuditLog = (workspace_id, params = {}) =>
  api.get(`/workspaces/${workspace_id}/audit`, { params }).then(r => r.data);

// Rename a workspace (leader+ only)
export const renameWorkspace = (workspace_id, name) =>
  api.patch(`/workspaces/${workspace_id}`, { name }).then(r => r.data);

// Welcome / activation flow — sets industry, flips Simulation Mode ON,
// seeds the demo dataset and returns counters for the Activación screen.
export const completeWelcomeOnboarding = (payload) =>
  api.post('/onboarding/welcome/complete', payload).then(r => r.data);

// Google OAuth (Gmail + Calendar) — Phase 7e
export const getGoogleIntegrationStatus = () =>
  api.get('/integrations/google/status').then(r => r.data);

export const startGoogleOAuth = (return_to = '/welcome/inbox') =>
  api.get('/integrations/google/start', { params: { return_to } }).then(r => r.data);

export const syncGoogleData = () =>
  api.post('/integrations/google/sync').then(r => r.data);

export const disconnectGoogle = () =>
  api.delete('/integrations/google/disconnect').then(r => r.data);

// Microsoft Outlook OAuth (Mail + Calendar) — Phase 7e.2
export const getMicrosoftIntegrationStatus = () =>
  api.get('/integrations/microsoft/status').then(r => r.data);

export const startMicrosoftOAuth = (return_to = '/welcome/inbox') =>
  api.get('/integrations/microsoft/start', { params: { return_to } }).then(r => r.data);

export const syncMicrosoftData = () =>
  api.post('/integrations/microsoft/sync').then(r => r.data);

export const disconnectMicrosoft = () =>
  api.delete('/integrations/microsoft/disconnect').then(r => r.data);

// Auto-sync toggle (works for any registered provider: 'google' | 'microsoft')
export const toggleAutoSync = (provider, paused) =>
  api.post(`/integrations/${provider}/auto-sync`, { paused }).then(r => r.data);

// Audit export — returns the raw Blob so callers can trigger a download.
// Accepts { format: 'csv'|'json', start_date, end_date, action }.
export const exportAuditLog = (workspace_id, params = {}) =>
  api
    .get(`/workspaces/${workspace_id}/audit/export`, {
      params,
      responseType: 'blob',
    })
    .then(r => {
      // Try to recover the filename the server proposed; fall back to a
      // sensible default if the header wasn't exposed by CORS.
      const disposition = r.headers?.['content-disposition'] || '';
      const match = disposition.match(/filename="?([^"]+)"?/i);
      const filename =
        match?.[1] ||
        `audit_${workspace_id}_${new Date().toISOString().replace(/[-:T.]/g, '').slice(0, 14)}.${params.format || 'csv'}`;
      return { blob: r.data, filename };
    });

// Dashboard
export const getDashboardMetrics = () => api.get('/dashboard/metrics').then(r => r.data);
export const getAISuggestions = () => api.get('/dashboard/suggestions').then(r => r.data);

// Inbox
export const getInbox = (status) => api.get('/inbox', { params: status ? { status } : {} }).then(r => r.data);
export const getInboxItem = (id) => api.get(`/inbox/${id}`).then(r => r.data);
export const analyzeInboxItem = (id) => api.post(`/inbox/${id}/analyze`).then(r => r.data);
export const approveInboxAction = (id) => api.post(`/inbox/${id}/approve`).then(r => r.data);
export const declineInboxAction = (id) => api.post(`/inbox/${id}/decline`).then(r => r.data);
export const batchAnalyzeInbox = (inbox_ids) => api.post('/inbox/batch-analyze', { inbox_ids }).then(r => r.data);
export const batchApproveInbox = (inbox_ids) => api.post('/inbox/batch-approve', { inbox_ids }).then(r => r.data);
export const updateInboxDetails = (id, data) => api.put(`/inbox/${id}/details`, data).then(r => r.data);
export const approveWithOverrides = (id, data) => api.post(`/inbox/${id}/approve-with-overrides`, data).then(r => r.data);

// Calendar
export const getCalendarEvents = () => api.get('/calendar').then(r => r.data);
export const createCalendarEvent = (data) => api.post('/calendar', data).then(r => r.data);
export const deleteCalendarEvent = (id) => api.delete(`/calendar/${id}`).then(r => r.data);

// Contacts
export const getContacts = (stage) => api.get('/contacts', { params: stage ? { lifecycle_stage: stage } : {} }).then(r => r.data);
export const getContact = (id) => api.get(`/contacts/${id}`).then(r => r.data);
export const createContact = (data) => api.post('/contacts', data).then(r => r.data);

// Agents
export const getAgents = () => api.get('/agents').then(r => r.data);
export const createAgent = (data) => api.post('/agents', data).then(r => r.data);

// Onboarding
export const updateOnboardingTask = (taskId, status) => api.put(`/onboarding/${taskId}`, { status }).then(r => r.data);

// Content
export const getContent = (type) => api.get('/content', { params: type ? { content_type: type } : {} }).then(r => r.data);
export const generateContent = (data) => api.post('/content/generate', data).then(r => r.data);
export const deleteContent = (id) => api.delete(`/content/${id}`).then(r => r.data);

// Activity
export const getActivity = (limit = 20, eventType) => api.get('/activity', { params: { limit, ...(eventType ? { event_type: eventType } : {}) } }).then(r => r.data);

// System
export const getSystemStatus = () => api.get('/system/status').then(r => r.data);

// Automation Policies
export const getPolicies = () => api.get('/policies').then(r => r.data);
export const createPolicy = (payload) => api.post('/policies', payload).then(r => r.data);
export const updatePolicy = (id, data) => api.put(`/policies/${id}`, data).then(r => r.data);
export const deletePolicy = (id) => api.delete(`/policies/${id}`).then(r => r.data);
export const evaluatePolicy = (inboxId) => api.get(`/policies/evaluate/${inboxId}`).then(r => r.data);

// Escalation Rules
export const getEscalationRules = () => api.get('/escalation-rules').then(r => r.data);
export const createEscalationRule = (data) => api.post('/escalation-rules', data).then(r => r.data);
export const updateEscalationRule = (id, data) => api.put(`/escalation-rules/${id}`, data).then(r => r.data);
export const deleteEscalationRule = (id) => api.delete(`/escalation-rules/${id}`).then(r => r.data);

// Content Templates
export const getTemplates = (category) => api.get('/templates', { params: category ? { category } : {} }).then(r => r.data);
export const getTemplate = (id) => api.get(`/templates/${id}`).then(r => r.data);
export const createTemplate = (data) => api.post('/templates', data).then(r => r.data);
export const updateTemplate = (id, data) => api.put(`/templates/${id}`, data).then(r => r.data);
export const deleteTemplate = (id) => api.delete(`/templates/${id}`).then(r => r.data);
export const generateFromTemplate = (id, context) => api.post(`/templates/${id}/generate`, { template_id: id, context }).then(r => r.data);

// Quantro Connect
export const getConnectProviders = () => api.get('/connect/providers').then(r => r.data);
export const getConnections = () => api.get('/connect/connections').then(r => r.data);
export const getConnectProvider = (provider) => api.get(`/connect/providers/${provider}`).then(r => r.data);
export const testConnection = (provider) => api.post(`/connect/providers/${provider}/test`).then(r => r.data);
export const syncConnection = (provider) => api.post(`/connect/providers/${provider}/sync`).then(r => r.data);
export const disconnectProvider = (provider) => api.delete(`/connect/providers/${provider}`).then(r => r.data);
export const connectFacturapi = (secret_key) => api.post('/connect/providers/facturapi/connect', { secret_key }).then(r => r.data);
export const requestGooglePermission = (action_id, return_to) =>
  api.get('/connect/providers/google/request-permission', { params: { action_id, return_to } }).then(r => r.data);

// Quantro Actions
export const getActions = (params = {}) => api.get('/actions', { params }).then(r => r.data);
export const getAction = (actionId) => api.get(`/actions/${actionId}`).then(r => r.data);
export const executeAction = (actionId, payload) => api.post(`/actions/${actionId}/execute`, payload).then(r => r.data);
export const getActionExecutions = (params = {}) => api.get('/actions/executions', { params }).then(r => r.data);
export const getActionExecution = (executionId) => api.get(`/actions/executions/${executionId}`).then(r => r.data);
export const approveActionExecution = (executionId) => api.post(`/actions/executions/${executionId}/approve`).then(r => r.data);
export const cancelActionExecution = (executionId) => api.post(`/actions/executions/${executionId}/cancel`).then(r => r.data);

export default api;
