import axios from 'axios';

const API_BASE = process.env.REACT_APP_BACKEND_URL || '';

const api = axios.create({
  baseURL: `${API_BASE}/api`,
  headers: { 'Content-Type': 'application/json' },
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

export default api;
