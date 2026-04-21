import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { Toaster } from './components/ui/sonner';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { BusinessProfileProvider } from './contexts/BusinessProfileContext';
import { LanguageProvider } from './context/LanguageContext';
import ProtectedRoute from './components/ProtectedRoute';
import Sidebar from './components/Sidebar';
import Dashboard from './pages/Dashboard';
import SmartInbox from './pages/SmartInbox';
import Schedule from './pages/Schedule';
import CRM from './pages/CRM';
import Onboarding from './pages/Onboarding';
import ContentEngine from './pages/ContentEngine';
import AutomationPolicies from './pages/AutomationPolicies';
import Settings from './pages/Settings';
import LoginPage from './pages/LoginPage';
import AuthCallback from './pages/AuthCallback';
import './App.css';

/**
 * AppShell — the authenticated layout (sidebar + content). Wrapped by
 * ProtectedRoute at the route level. We mount BusinessProfileProvider
 * INSIDE the authenticated shell so it only fires API calls once a user
 * is signed in and a workspace is active.
 */
function AppShell() {
  return (
    <BusinessProfileProvider>
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
      </div>
    </BusinessProfileProvider>
  );
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/auth/callback" element={<AuthCallback />} />
      <Route
        path="/*"
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      />
    </Routes>
  );
}

function App() {
  return (
    <LanguageProvider>
      <AuthProvider>
        <Router>
          <AppRoutes />
          <Toaster position="bottom-right" theme="dark" />
        </Router>
      </AuthProvider>
    </LanguageProvider>
  );
}

export default App;
