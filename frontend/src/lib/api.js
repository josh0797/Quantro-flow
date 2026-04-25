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

export default api;
