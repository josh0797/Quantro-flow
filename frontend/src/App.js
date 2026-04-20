import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { Toaster } from './components/ui/sonner';
import { BusinessProfileProvider } from './contexts/BusinessProfileContext';
import Sidebar from './components/Sidebar';
import Dashboard from './pages/Dashboard';
import SmartInbox from './pages/SmartInbox';
import Schedule from './pages/Schedule';
import CRM from './pages/CRM';
import Onboarding from './pages/Onboarding';
import ContentEngine from './pages/ContentEngine';
import AutomationPolicies from './pages/AutomationPolicies';
import Settings from './pages/Settings';
import './App.css';

function App() {
  return (
    <BusinessProfileProvider>
      <Router>
        <div className="app-shell dark">
          <div className="gradient-wash" />
          <Sidebar />
          <main className="main-content">
            <Routes>
              <Route path="/" element={<Navigate to="/dashboard" replace />} />
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/inbox" element={<SmartInbox />} />
              <Route path="/schedule" element={<Schedule />} />
              <Route path="/crm" element={<CRM />} />
              <Route path="/onboarding" element={<Onboarding />} />
              <Route path="/content" element={<ContentEngine />} />
              <Route path="/automation" element={<AutomationPolicies />} />
              <Route path="/automation-policies" element={<AutomationPolicies />} />
              <Route path="/settings" element={<Settings />} />
            </Routes>
          </main>
          <Toaster position="bottom-right" theme="dark" />
        </div>
      </Router>
    </BusinessProfileProvider>
  );
}

export default App;
