// Industry-specific configurations for dynamic dashboard and UI

export const INDUSTRIES = [
  { value: 'real_estate', label: 'Real Estate' },
  { value: 'healthcare', label: 'Healthcare' },
  { value: 'consulting', label: 'Consulting' },
  { value: 'ecommerce', label: 'E-commerce' },
  { value: 'other', label: 'Other' }
];

export const INDUSTRY_CONFIG = {
  real_estate: {
    name: 'Real Estate',
    kpis: {
      team: { label: 'Active Agents', icon: 'users' },
      schedule: { label: 'Upcoming Viewings', icon: 'calendar' },
      inbox: { label: 'Inbox Requests', icon: 'inbox' },
      crm: { label: 'CRM Contacts Synced', icon: 'database' }
    },
    aiSuggestions: [
      { text: 'Analyze property viewing request', priority: 'high' },
      { text: 'Send buyer follow-up email', priority: 'medium' },
      { text: 'Route urgent offer update to team', priority: 'high' },
      { text: 'Schedule open house event', priority: 'low' }
    ],
    activities: [
      { type: 'inbox', text: 'New property inquiry received', time: '2m ago' },
      { type: 'schedule', text: 'Viewing scheduled for 123 Main St', time: '15m ago' },
      { type: 'crm', text: 'CRM synced with 3 new leads', time: '1h ago' },
      { type: 'ai', text: 'AI classified 5 inbox items', time: '2h ago' }
    ],
    eventTypes: ['Viewing', 'Open House', 'Client Meeting', 'Team Sync'],
    entityDefaults: {
      contacts: 'Contacts',
      team_members: 'Agents',
      meetings: 'Viewings',
      events: 'Open Houses',
      services: 'Listings'
    }
  },
  healthcare: {
    name: 'Healthcare',
    kpis: {
      team: { label: 'Active Patients', icon: 'users' },
      schedule: { label: 'Upcoming Appointments', icon: 'calendar' },
      inbox: { label: 'Intake Requests', icon: 'inbox' },
      crm: { label: 'Records Synced', icon: 'database' }
    },
    aiSuggestions: [
      { text: 'Review patient intake request', priority: 'high' },
      { text: 'Confirm patient follow-up appointment', priority: 'medium' },
      { text: 'Escalate urgent appointment issue', priority: 'high' },
      { text: 'Generate care coordination summary', priority: 'low' }
    ],
    activities: [
      { type: 'inbox', text: 'New appointment request received', time: '5m ago' },
      { type: 'schedule', text: 'Consultation appointment confirmed', time: '20m ago' },
      { type: 'crm', text: 'Patient records updated', time: '45m ago' },
      { type: 'ai', text: 'AI processed 8 intake forms', time: '1h ago' }
    ],
    eventTypes: ['Appointment', 'Consultation', 'Follow-up', 'Staff Meeting'],
    entityDefaults: {
      contacts: 'Patients',
      team_members: 'Staff',
      meetings: 'Appointments',
      events: 'Care Events',
      services: 'Services'
    }
  },
  consulting: {
    name: 'Consulting',
    kpis: {
      team: { label: 'Active Clients', icon: 'users' },
      schedule: { label: 'Upcoming Calls', icon: 'calendar' },
      inbox: { label: 'New Inquiries', icon: 'inbox' },
      crm: { label: 'CRM Contacts Synced', icon: 'database' }
    },
    aiSuggestions: [
      { text: 'Qualify new lead inquiry', priority: 'high' },
      { text: 'Prepare discovery call follow-up', priority: 'medium' },
      { text: 'Generate proposal draft for client', priority: 'high' },
      { text: 'Schedule strategy session', priority: 'low' }
    ],
    activities: [
      { type: 'inbox', text: 'New consulting inquiry received', time: '3m ago' },
      { type: 'schedule', text: 'Discovery call scheduled', time: '25m ago' },
      { type: 'crm', text: 'Client profile updated', time: '1h ago' },
      { type: 'ai', text: 'AI classified 6 lead requests', time: '2h ago' }
    ],
    eventTypes: ['Discovery Call', 'Strategy Session', 'Client Review', 'Workshop'],
    entityDefaults: {
      contacts: 'Clients',
      team_members: 'Consultants',
      meetings: 'Calls',
      events: 'Workshops',
      services: 'Services'
    }
  },
  ecommerce: {
    name: 'E-commerce',
    kpis: {
      team: { label: 'Active Customers', icon: 'users' },
      schedule: { label: 'Open Support Requests', icon: 'calendar' },
      inbox: { label: 'Order Issues', icon: 'inbox' },
      crm: { label: 'CRM Contacts Synced', icon: 'database' }
    },
    aiSuggestions: [
      { text: 'Review priority support ticket', priority: 'high' },
      { text: 'Draft refund response email', priority: 'medium' },
      { text: 'Escalate fulfillment issue to ops', priority: 'high' },
      { text: 'Schedule campaign review meeting', priority: 'low' }
    ],
    activities: [
      { type: 'inbox', text: 'Customer support request received', time: '1m ago' },
      { type: 'schedule', text: 'Refund flagged for review', time: '10m ago' },
      { type: 'crm', text: 'Customer profile synced', time: '30m ago' },
      { type: 'ai', text: 'AI classified 12 support tickets', time: '1h ago' }
    ],
    eventTypes: ['Support Review', 'Campaign Planning', 'Operations Meeting', 'Product Launch'],
    entityDefaults: {
      contacts: 'Customers',
      team_members: 'Support Team',
      meetings: 'Reviews',
      events: 'Campaigns',
      services: 'Products'
    }
  },
  other: {
    name: 'Business',
    kpis: {
      team: { label: 'Team Members', icon: 'users' },
      schedule: { label: 'Upcoming Meetings', icon: 'calendar' },
      inbox: { label: 'Inbox Requests', icon: 'inbox' },
      crm: { label: 'CRM Contacts Synced', icon: 'database' }
    },
    aiSuggestions: [
      { text: 'Process new request', priority: 'high' },
      { text: 'Send follow-up communication', priority: 'medium' },
      { text: 'Route item to appropriate team', priority: 'high' },
      { text: 'Schedule team meeting', priority: 'low' }
    ],
    activities: [
      { type: 'inbox', text: 'New request received', time: '4m ago' },
      { type: 'schedule', text: 'Meeting scheduled', time: '30m ago' },
      { type: 'crm', text: 'Contact record updated', time: '1h ago' },
      { type: 'ai', text: 'AI processed 7 items', time: '2h ago' }
    ],
    eventTypes: ['Meeting', 'Call', 'Review', 'Workshop'],
    entityDefaults: {
      contacts: 'Contacts',
      team_members: 'Team Members',
      meetings: 'Meetings',
      events: 'Events',
      services: 'Services'
    }
  }
};

export function getIndustryConfig(industry) {
  return INDUSTRY_CONFIG[industry] || INDUSTRY_CONFIG.other;
}

export function getEntityLabel(industry, entityType, customLabels = {}) {
  // Custom labels take priority
  if (customLabels[entityType]) {
    return customLabels[entityType];
  }
  
  // Fall back to industry defaults
  const config = getIndustryConfig(industry);
  return config.entityDefaults[entityType] || entityType;
}
